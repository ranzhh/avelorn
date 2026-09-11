"""Compile rule effects into attack modifiers.

Printed rule names on units and weapons resolve against the rule
entries under ``data/tow/rules/``; a resolved rule's effects compile
into :class:`~avelorn.tow.engine.attack.Modifier` records the dice walk
interprets. Resolution honours the convention the rules themselves print:
a bracketed number after the name ("Armour Bane (1)") is the parameter
of the rule filed under the "(X)" placeholder ("the amount shown in
brackets after the name of this special rule").

Every modifier compiles through one path: evaluate its engagement
condition, look up the roll its kind changes — each kind's meaning is
declared once, in the table of rolls — and hook the walk there: before
the roll for an unconditional change, on the trigger die's success for
an ``on_natural`` one. New conditional-modifier rules are data through
this path, not new code; only mechanics no modifier can express earn a
kind (and a handler) of their own.

Compilation is all-or-nothing per rule: if any effect names a trigger
the engine cannot honour, or needs a parameter the printed name did
not supply, the whole rule stays unfactored — reported, never
partially or silently applied. A rule with no effects at all is
likewise unfactored: recognised text the engine cannot yet honour.
A rule that is simply not *this* compile's business — its dice belong
to the other seat of the attack — is neither: it is inapplicable, the
third bucket, claimed by whoever resolves that seat too.
"""

import logging
import re
from collections.abc import Collection, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from fractions import Fraction
from typing import get_args

from pydantic.fields import FieldInfo

from avelorn.core.distribution import Distribution
from avelorn.core.registry import Registry, UnknownNameError
from avelorn.tow.engine.attack import (
    AttackProfile,
    Modifier,
    Reroll,
    RollState,
    Transform,
)
from avelorn.tow.engine.attack import Outcome as AttackOutcome
from avelorn.tow.schema.psychology import Outcome
from avelorn.tow.schema.rule import (
    PARAMETER_SUFFIX,
    Add,
    AttackKind,
    AttackMarkEffect,
    BarEffect,
    BlowEffect,
    Bounded,
    ChoiceEffect,
    Comparison,
    Decision,
    DiceQuantity,
    Gate,
    GatedEffect,
    GrantEffect,
    HitOrder,
    HitsEffect,
    MembershipGate,
    ModifierEffect,
    NaturalRoll,
    Quantity,
    ReplaceEffect,
    RerollEffect,
    Rule,
    RuleEffect,
    Seam,
    VolleyEffect,
    WoundMultiplierEffect,
    seam_of,
)
from avelorn.tow.schema.stage import Dice, Side, Stage
from avelorn.tow.schema.unit import Characteristic, TroopType
from avelorn.tow.schema.weapon import WeaponType

logger = logging.getLogger(__name__)

_PARAMETERISED = re.compile(r"^(?P<base>.+) \((?P<value>[^()]+)\)$")

# The attack sequence's order, for "can this die still shape that roll".
_SEQUENCE = {stage: position for position, stage in enumerate(Stage)}


@dataclass(frozen=True)
class ChargeEvent:
    """The model's own charge this turn — the charge event and its properties.

    Built by a producer when the model charged; a gate navigates its
    properties (``charging.distance``). New properties (the arc, the number of
    enemy models charged) join here and on :class:`~avelorn.tow.schema.rule.ChargeGate`
    together — a drift guard keeps the two in step.
    """

    distance: int  # inches of the charge move


@dataclass(frozen=True)
class CombatFacts:
    """The evaluated facts of the close combat — the values behind a CombatGate."""

    first_round: bool | None = None
    outnumbers: bool | None = None
    was_charged: bool | None = None


@dataclass(frozen=True)
class MovementFacts:
    """The evaluated facts of the model's move — the values behind a MovementGate.

    ``charge`` is None when the model did not charge (known, not unknown — a
    model's movement is settled this turn); otherwise it carries the charge's
    properties.
    """

    moved: bool | None = None
    charge: ChargeEvent | None = None


@dataclass(frozen=True)
class ShootingFacts:
    """The evaluated facts of the volley — the values behind a ShootingGate."""

    at_long_range: bool | None = None
    stand_and_shoot: bool | None = None


@dataclass(frozen=True)
class WeaponFacts:
    """The evaluated facts of the weapon in hand — the values behind a WeaponGate.

    The weapon a model is acting with, as the walk and the folds see it: its
    ``type`` (the weapon family) and ``name``, either None when nothing is armed
    (a rule gating on the weapon in hand is then unevaluatable, reported).
    """

    type: WeaponType | None = None
    name: str | None = None


@dataclass(frozen=True)
class ArmourFacts:
    """The evaluated facts of one piece of armour worn — behind an ArmourGate.

    A single piece, by printed ``name`` (armour has no family axis). The pieces a
    model wears are held as a collection on the context, and an
    :class:`~avelorn.tow.schema.rule.ArmourGate` is satisfied by any one of them
    that matches — so this is the *member*, not the subject.
    """

    name: str | None = None


@dataclass(frozen=True)
class FoeFacts:
    """The evaluated facts of the foe the bearer's attack lands on — behind a FoeGate.

    Produced where the foe is in hand (the combat contexts, which already
    weigh it for outnumbering); a context that never met one leaves the
    subject None, and a foe-gated rule there is settled by its other
    conjuncts or reported.
    """

    troop_type: TroopType | None = None


@dataclass(frozen=True)
class AttackFacts:
    """The evaluated facts of the incoming attack — the values behind an AttackGate.

    ``magical`` and ``flaming`` are read from the striker's resolved rules —
    the profile in use's and the unit's own alike (:func:`attack_marks`), as
    the printed sentences confer either way. ``at_long_range`` duplicates
    :attr:`ShootingFacts.at_long_range` so a defender's rule can read it; a
    mistake kept for now, see #179 before adding a fifth field here.
    """

    kind: AttackKind | None = None
    magical: bool | None = None
    flaming: bool | None = None
    at_long_range: bool | None = None


@dataclass(frozen=True)
class GateContext:
    """The evaluated facts a gate is tested against, mirroring the When tree.

    One facts object per subject, the peer of the schema's gate models: a
    producer builds one for its phase, filling the facts that phase knows, and
    the evaluator walks an effect's :class:`~avelorn.tow.schema.rule.When`
    against it, subject by subject and property by property. A state fact is
    None when unknown (the tri-state the gate carries).

    ``combat`` and ``target_of`` are presence entities: None means the model is
    not engaged in a close combat / is not the target of an attack (known, not
    unknown), so a rule gating on them is honoured as not-applying. The
    always-present subjects (``movement``, ``shooting``, ``wielding``) keep
    default facts a phase never sets — an unarmed ``wielding`` (both fields None)
    leaves a weapon-in-hand gate unevaluatable, reported, rather than False.

    ``worn`` is the one collection subject (a model wears several pieces of
    armour), and it reads its None the third way: **not offered**, so a gate on
    the armour worn is unevaluatable and reported. The empty tuple is what "wears
    nothing" looks like — known, settling such a gate False — which is precisely
    why the None is free to mean unknown here where a presence entity's None
    means known-absent: a collection can spell absence as ``()``, an entity has
    no spare value to spell it with. A producer holding a loadout always passes
    the pieces, empty or not; one that never looked leaves the None it cannot
    honestly fill.
    """

    combat: CombatFacts | None = None
    movement: MovementFacts = field(default_factory=MovementFacts)
    shooting: ShootingFacts = field(default_factory=ShootingFacts)
    wielding: WeaponFacts = field(default_factory=WeaponFacts)
    worn: tuple[ArmourFacts, ...] | None = None
    target_of: AttackFacts | None = None
    # An attack always has a foe, so the subject is always present — like
    # ``wielding``, default facts a producer never filled read as unknown,
    # never as a foe that did not occur.
    foe: FoeFacts = field(default_factory=FoeFacts)


def _as_context(context: GateContext | None) -> GateContext:
    """Normalise an optional context into one; None means all facts unknown.

    Returns:
        The context itself, or an empty context (every fact at its default).
    """
    return context if context is not None else GateContext()


def printed_rule(printed: str, rules: Registry[Rule]) -> Rule | None:
    """Resolve a printed rule name to the rule exactly as printed.

    An exact name match returns the entry itself. Otherwise a bracketed
    numeric parameter matches the rule filed under the "(X)" placeholder
    and returns a copy carrying the printed name, the parameter
    substituted into its effects ("the amount shown in brackets after
    the name of this special rule") — the rule as this unit prints it,
    not as it is filed. A name the registry does not know is not an
    error here but the answer — the rule is not modelled yet — so this
    is the seam where the registry's loud :class:`UnknownNameError`
    becomes the domain's quiet None, and unfactored reporting takes
    over.

    Returns:
        The rule as printed, or None if nothing matches.
    """
    with suppress(UnknownNameError):
        return rules.by_name(printed)
    if match := _PARAMETERISED.match(printed):
        with suppress(UnknownNameError):
            entry = rules.by_name(match.group("base") + PARAMETER_SUFFIX)
            parameter = _parameter(match.group("value"))
            if parameter is None:
                return None
            effects = [_with_parameter(effect, parameter) for effect in entry.effects]
            return entry.model_copy(update={"name": printed, "effects": effects})
    return None


def _parameter(printed: str) -> int | DiceQuantity | None:
    # The bracketed parameter as printed: a number ("Armour Bane (1)") or a
    # dice quantity ("Impact Hits (D6)", "Stomp Attacks (D3+1)"). Any other
    # text is no parameter at all — the name does not resolve.
    if printed.isdigit():
        return int(printed)
    return DiceQuantity.parse(printed)


def _with_parameter(effect: RuleEffect, parameter: int | DiceQuantity) -> RuleEffect:
    # Substitute the printed parameter into every "X" placeholder the
    # effect carries, looking inside mappings (an operation's amounts).
    # Introspects the effect's fields, so a new X-bearing field
    # participates automatically. An operation's amounts are numbers, so a
    # dice parameter substitutes into bare fields only — a mapping's "X"
    # then stays unbound, and the rule reports unfactored rather than
    # carrying a quantity its seam cannot read. What does bind revalidates
    # through the effect's own model, so a bound value the field's own
    # validators reject ("Multiple Wounds (1)") fails loudly rather than
    # slipping past them on a copy.
    placeholders: dict = {}
    for name in type(effect).model_fields:
        value = getattr(effect, name)
        if value == "X":
            placeholders[name] = parameter
        elif isinstance(value, Mapping) and isinstance(parameter, int):
            bound = {key: _bind(amount, parameter) for key, amount in value.items()}
            if bound != dict(value):
                placeholders[name] = bound
    if not placeholders:
        return effect
    fields = type(effect).model_fields
    substituted = {
        **effect.model_dump(by_alias=True),
        **{fields[name].alias or name: value for name, value in placeholders.items()},
    }
    return type(effect).model_validate(substituted)


def _bind(amount: object, parameter: int) -> object:
    # One operation amount with the parameter bound into its "X", in either
    # spelling: a bare amount, or one carrying a printed bound, where the
    # placeholder sits a level down and would otherwise never be found.
    if amount == "X":
        return parameter
    if isinstance(amount, Bounded) and amount.amount == "X":
        return amount.model_copy(update={"amount": parameter})
    return amount


class _Disposition(Enum):
    """Where a compiled effect — and so its rule — lands: in the math, or why not.

    The three buckets :class:`CompiledRules` reports, as the verdict one
    compile step returns.
    """

    FACTORED = auto()
    UNFACTORED = auto()
    INAPPLICABLE = auto()


# One compile step's verdict: the bucket, and whatever modifiers it produced
# (none for every bucket but a factored effect that also applies).
_Verdict = tuple[_Disposition, Sequence[Modifier | Transform]]
_UNFACTORED: _Verdict = (_Disposition.UNFACTORED, ())
_INAPPLICABLE: _Verdict = (_Disposition.INAPPLICABLE, ())
_HONOURED: _Verdict = (_Disposition.FACTORED, ())


@dataclass(frozen=True)
class CompiledRules:
    """What one walk-compile made of a list of printed rule names.

    ``modifiers`` are the records the dice walk applies. The three name
    lists partition the names compiled — every one lands in exactly one, so
    a caller can report a rule's disposition without double-counting:

    - ``factored``: this walk owns the rule's effects and evaluated them in,
      or honoured them by not applying (a gate answered False).
    - ``inapplicable``: every effect belongs to the *other seat* of this
      walk, so this compile is not the one that owns it. The same rule
      compiles from its proper seat, so a caller resolving both seats
      (:func:`~avelorn.tow.phases.combat.fight`) claims it — the other
      seat's compile has it — while a one-sided caller keeps reporting it,
      because no seat there consumed it.
    - ``unfactored``: nothing here the walk can honour — the rule is
      unmodelled, effect-less, needs a fact the conditions leave unknown, or
      speaks to another *seam* entirely (a characteristic, a rank depth, a
      re-roll). Another seam's fold has its own say on such a rule, so the
      caller claims it from there or reports it; no seat of this walk ever
      will, which is exactly why it is not ``inapplicable``.
    """

    modifiers: tuple[Modifier, ...] = ()
    # Bespoke walk hooks a declarative effect compiled to (a blow's denial
    # and escalation) — applied beside the modifiers, claimed the same way.
    transforms: tuple[Transform, ...] = ()
    factored: tuple[str, ...] = ()
    unfactored: tuple[str, ...] = ()
    inapplicable: tuple[str, ...] = ()


def compile_rules(
    printed_rules: Sequence[str],
    resolved: Mapping[str, Rule],
    conditions: "GateContext | None" = None,
    *,
    seat: Side = Side.ATTACKER,
    grants: "Mapping[str, Rule] | None" = None,
) -> CompiledRules:
    """Compile printed rule names into modifier records.

    ``resolved`` maps printed names to their rules as printed — built at
    the muster boundary (a loadout's ``weapon_rules``) or from a registry
    scan; a name absent from it is not modelled. ``conditions`` is the
    evaluated :class:`GateContext` (or None for all-unknown). ``seat`` is
    the side of the attack the rules' bearer occupies in the walk being
    compiled — the attacker's rules compile at ``ATTACKER``, the target's
    at ``TARGET``, both into the same walk. An effect reaches the walk iff
    its quantity's owner side (flipped by the effect's printed ``enemy``
    subject) matches the seat; one for the other seat is *inapplicable*
    here — the same rule compiles from its proper seat in the walks where
    it matters. ``grants`` maps the printed names of rules *conferred* by a
    grant effect to their resolved entries (a loadout's ``granted_rules``) —
    the lookup a :class:`~avelorn.tow.schema.rule.GrantEffect` expands
    through; a granted name absent from it is unfactored, like any
    unmodelled rule. A rule whose gate needs an unknown fact is unfactored
    and reported; a rule whose gate evaluates False is factored, honoured by
    not applying — no modifier, no note.

    Whether the walk owns an effect at all is decided from the effect alone,
    before any gate: a rule speaking to another seam is reported the same
    whether the facts happen to answer its condition False or not.

    Returns:
        The modifier records and each printed name's disposition — factored,
        inapplicable, or unfactored (see :class:`CompiledRules`).
    """
    context = _as_context(conditions)
    modifiers: list[Modifier] = []
    transforms: list[Transform] = []
    buckets: dict[_Disposition, list[str]] = {disposition: [] for disposition in _Disposition}
    for printed in printed_rules:
        rule = resolved.get(printed)
        if rule is None:
            buckets[_Disposition.UNFACTORED].append(printed)
            continue
        disposition, compiled = _compile(rule, context, grants, seat, printed)
        buckets[disposition].append(printed)
        if compiled:
            logger.debug("rule factored: %s -> %d record(s)", printed, len(compiled))
        for record in compiled:
            if isinstance(record, Modifier):
                modifiers.append(record)
            else:
                transforms.append(record)
    return CompiledRules(
        tuple(modifiers),
        tuple(transforms),
        tuple(buckets[_Disposition.FACTORED]),
        tuple(buckets[_Disposition.UNFACTORED]),
        tuple(buckets[_Disposition.INAPPLICABLE]),
    )


def factored_notes(
    rules: Sequence[Rule],
    factored: Collection[str],
    source: str,
    granted: "Mapping[str, Rule] | None" = None,
) -> list[str]:
    """The authored ``notes`` of the factored rules that carry them.

    A rule's hand-authored :attr:`~avelorn.tow.schema.rule.Rule.notes` (its
    modelling scope) surface wherever the rule was factored, labelled by rule
    and ``source`` (the unit) — the generic relay every seam shares, so a
    caveat is stated in the rule's data and shown beside the figure it
    qualifies, never composed as prose in the engine.

    ``granted`` extends the sweep to conferred rules (a loadout's
    ``granted_rules``): a factored rule's grants are looked up and their own
    notes relayed too, so a caveat authored on a grant-only entry (Enemy
    Fire (Skirmishers)'s Unit Strength scope) is not silenced by living
    outside the unit's printed list. The granting rule's factoring is the
    proxy for the grant's — a grant honoured as not firing still surfaces
    its caveat, which errs on the side of saying it.

    Returns:
        One note per factored rule (or rule it grants) that authored some.
    """
    notes: dict[str, None] = {}  # insertion-ordered dedup: two grants, one note
    for rule in rules:
        if rule.name not in factored:
            continue
        if rule.notes:
            notes[f"{rule.name} ({source}): {rule.notes}"] = None
        for effect in rule.effects:
            if isinstance(effect, GrantEffect):
                conferred = (granted or {}).get(effect.grants)
                if conferred is not None and conferred.notes:
                    notes[f"{conferred.name} ({source}): {conferred.notes}"] = None
    return list(notes)


def forced_outcome(
    rules: Sequence[Rule], decision: Decision
) -> tuple[Outcome | None, Rule | None]:
    """The outcome a contingent's rules force at ``decision``, and the rule forcing it.

    The generic read a seam owning a decision makes — "is my decision forced,
    and to what?" — over the ungated :class:`~avelorn.tow.schema.rule.ChoiceEffect`
    that carries it. A gated one needs a context the seam here lacks, so it is
    left to roll rather than applied blind. The value is the base ``Outcome``;
    the caller knows the concrete subset its decision uses.

    Returns:
        The forced outcome and the rule that carries it, or ``(None, None)``
        when nothing forces this decision.
    """
    for rule in rules:
        for effect in rule.effects:
            if (
                isinstance(effect, ChoiceEffect)
                and effect.when is None
                and decision in effect.forces
            ):
                return effect.forces[decision], rule
    return None, None


def outcome_substitutions(
    rules: Sequence[Rule],
    decision: Decision,
    conditions: "GateContext | None" = None,
) -> list[tuple[Outcome, Outcome, Rule]]:
    """The outcome substitutions a contingent's rules make at ``decision``.

    The reader of :class:`~avelorn.tow.schema.rule.ReplaceEffect` — a choice
    that replaces one outcome with another and leaves the rest rolled,
    Shieldwall's "may Give Ground rather than Fall Back in Good Order" —
    gated on the evaluated ``conditions`` (a gate the facts cannot answer
    leaves the rule unapplied, reported by the caller as ever). Each entry
    reads (replaced, taken, rule).

    Returns:
        The substitutions whose gates hold, in rule order.
    """
    context = _as_context(conditions)
    found: list[tuple[Outcome, Outcome, Rule]] = []
    for rule in rules:
        for effect in rule.effects:
            if (
                isinstance(effect, ReplaceEffect)
                and decision in effect.replaces
                and _gate_applies(effect, context) is True
            ):
                found.extend(
                    (replaced, taken, rule)
                    for replaced, taken in effect.replaces[decision].items()
                )
    return found


def _compile(
    rule: Rule,
    context: GateContext,
    grants: "Mapping[str, Rule] | None" = None,
    seat: Side = Side.ATTACKER,
    printed: str | None = None,
) -> _Verdict:
    # All-or-nothing per rule: one effect the walk cannot honour leaves the
    # whole rule unfactored, whatever the others gave. A rule whose *every*
    # effect is the other seat's is inapplicable — nothing in it is this
    # compile's business. Anything else is factored, including an effect whose
    # condition evaluates False: honoured with no modifiers, not unfactored.
    if not rule.effects:
        return _UNFACTORED
    records: list[Modifier | Transform] = []
    dispositions: set[_Disposition] = set()
    for effect in rule.effects:
        disposition, compiled = _compile_effect(
            effect, context, grants, seat, printed or rule.name
        )
        if disposition is _Disposition.UNFACTORED:
            return _UNFACTORED
        dispositions.add(disposition)
        records.extend(compiled)
    if dispositions == {_Disposition.INAPPLICABLE}:
        return _INAPPLICABLE
    return _Disposition.FACTORED, records


@dataclass(frozen=True)
class _Roll:
    """The roll a modifier kind changes: where it happens, how its target moves, whose it is."""

    stage: Stage  # the stage whose roll the kind's quantity decides
    sign: int  # multiplies the printed amount into target movement
    side: Side  # whose quantity it is — not always whose die it lands on


# What each roll-seam quantity means, declared once; a drift-guard test keeps
# it covering every roll-seam Quantity. The printed sign conventions differ
# per quantity, and ``sign`` carries them: To Hit modifiers speak roll-side
# (a -1 penalty *raises* the target, so the target moves against the amount),
# Armour Piercing speaks piercing-side (a +1 improvement worsens the save
# target by the same amount). What a moved target *means* — a 7+ that
# confirms, a save that cannot be attempted — is each roll's own knowledge,
# in the walk, never stated here. ``side`` is the quantity's owner: both are
# characteristics of the *attack* (Armour Piercing is the attacker's even
# though it lands on the target's save die); a target-owned roll quantity
# (a ward-save modifier, say) would join with ``Side.TARGET``. An effect
# reaches the walks where its bearer sits on that side — flipped when the
# printed sentence's subject is the enemy.
_ROLLS: Mapping[Quantity, _Roll] = {
    Quantity.TO_HIT: _Roll(Stage.ROLL_TO_HIT, sign=-1, side=Side.ATTACKER),
    Quantity.ARMOUR_PIERCING: _Roll(Stage.MAKE_ARMOUR_SAVES, sign=+1, side=Side.ATTACKER),
}


def _compile_effect(
    effect: RuleEffect,
    context: GateContext,
    grants: "Mapping[str, Rule] | None" = None,
    seat: Side = Side.ATTACKER,
    source: str | None = None,
) -> _Verdict:
    # One effect, top to bottom, structural first: what this walk can never
    # honour is read off the effect alone — before any gate, so the verdict
    # never turns on the facts' luck — then the seat, then the when's state,
    # then each additive entry as data: which roll's target moves, by how
    # much, on which natural face.
    if isinstance(effect, GrantEffect):
        # A grant confers a named rule under its own outer gate; the granted
        # rule's own effects (kept with their inner gates) compile in its place.
        return _compile_grant(effect, context, grants, seat)
    if isinstance(effect, BlowEffect):
        # A blow is the attacker's alone: it denies the foe's save and may
        # escalate the outcome, so it compiles only from the attacker's seat
        # — the target's compile of the same rule is inapplicable, exactly
        # as an enemy-subject modifier's would be.
        if seat is not Side.ATTACKER:
            return _INAPPLICABLE
        applies = _gate_applies(effect, context)
        if applies is None:
            return _UNFACTORED
        if not applies:
            return _HONOURED
        return _Disposition.FACTORED, [_blow_transform(effect)]
    if not isinstance(effect, ModifierEffect):
        # Effects for other seams (e.g. re-rolls on make-panic-tests)
        # are not attack modifiers; their seams consume them directly.
        # Unfactored here, and claimed by the seam that owns them — never
        # inapplicable, which is the other *seat* of this walk's word alone.
        return _UNFACTORED
    if effect.set_:
        # A set replaces a base value, which the effective-value query reads,
        # not the walk (the walk only moves a roll's target). A set on a roll
        # quantity is rejected at load, so any set reaching here belongs to
        # another seam — unfactored, exactly as the characteristic and rank
        # adds below are.
        return _UNFACTORED
    adds = effect.add or {}
    rolls = [
        _ROLLS[quantity]
        for quantity in adds
        if isinstance(quantity, Quantity) and quantity in _ROLLS
    ]
    if len(rolls) != len(adds):
        # The walk handles only roll quantities (the _ROLLS vocabulary). A
        # characteristic is the effective-characteristic query's, a rank
        # quantity the fighting-rank query's, and each of those folds has its
        # own say on the rule. Settled here, ahead of the gate, so the same
        # rule is reported the same whether the facts answer its condition
        # False (a combat rule read in a volley) or leave it open.
        return _UNFACTORED
    amounts = [amount for amount in adds.values() if isinstance(amount, int)]
    if len(amounts) != len(adds):
        # An unsubstituted "X" placeholder: the printed name carried no parameter.
        return _UNFACTORED
    natural = effect.natural
    if natural is not None and any(
        _SEQUENCE[natural.roll] >= _SEQUENCE[roll.stage] for roll in rolls
    ):
        # A die can only shape rolls still to come; an event at or after the
        # changed roll cannot be honoured.
        return _UNFACTORED
    # The seat gate, before the state gate: an effect whose quantity belongs
    # to the other seat of this walk (its owner side, flipped when the printed
    # subject is the enemy) is no business of this compile whatever its facts
    # say — inapplicable, never unfactored. It compiles from its proper seat
    # in the walks where it applies. One effect speaks to one seam, so the
    # sides agree.
    sides = {roll.side for roll in rolls}
    if effect.enemy:
        sides = {side.other for side in sides}
    if sides != {seat}:
        return _INAPPLICABLE
    applies = _gate_applies(effect, context)
    if applies is None:
        return _UNFACTORED  # the context cannot answer the condition
    if not applies:
        return _HONOURED  # honoured: the situation does not arise
    return (
        _Disposition.FACTORED,
        [
            Modifier(lands_on=roll.stage, move=roll.sign * amount, trigger=natural, source=source)
            for roll, amount in zip(rolls, amounts, strict=True)
        ],
    )


def _blow_transform(effect: BlowEffect) -> Transform:
    # The blow as the walk speaks it: on the trigger's face, the denied save
    # takes no roll for the rest of this attack, and — for a slaying blow —
    # an unsaved wound resolves as the rulebook's Instant Kill. The walk
    # rolls the ward after the armour save untouched, which is the printed
    # "(Ward saves can be attempted as normal)"; an automatic roll shows no
    # face, so the trigger cannot fire — the printed automatic-wound
    # exception, emerging from the model.
    trigger = effect.natural
    assert trigger is not None  # the schema requires the trigger
    denied, slays = tuple(effect.denies), effect.slays

    def on_success(face: int, profile: AttackProfile) -> AttackProfile:
        if face != trigger.face:
            return profile
        for stage in denied:
            profile = profile.with_target(stage, RollState.IMPOSSIBLE)
        if slays:
            profile = replace(profile, unsaved_outcome=AttackOutcome.INSTANT_KILL)
        return profile

    return Transform(stage=trigger.roll, on_success=on_success)


def _compile_grant(
    effect: GrantEffect,
    context: GateContext,
    grants: "Mapping[str, Rule] | None",
    seat: Side = Side.ATTACKER,
) -> _Verdict:
    # A grant confers a named rule under its own *outer* gate: evaluate that gate,
    # then — when it holds — compile the granted rule in its place, its own
    # effects keeping their *inner* gates (Armour Bane's natural-6 To Wound). The
    # two gates conjoin without merging the trees. The grant stacks with any
    # instance the model already carries, because each is compiled independently.
    # The granted rule compiles at the grantee's seat: its effects carry their
    # own subjects, so a granted enemy-subject rule still reaches the right dice
    # — and a grant conferring nothing but the other seat's business is
    # inapplicable here, exactly as the rule itself would be.
    applies = _gate_applies(effect, context)
    if applies is None:
        return _UNFACTORED  # the context cannot answer the grant's gate
    if not applies:
        return _HONOURED  # honoured: the grant does not fire
    granted = (grants or {}).get(effect.grants)
    if granted is None:
        return _UNFACTORED  # the granted rule is not resolvable/modelled
    return _compile(granted, context, grants, seat, granted.name)


@dataclass(frozen=True)
class EffectiveValue:
    """A base quantity read with rule-granted modifiers applied.

    The result of folding a contingent's rules over one base value —
    whatever the quantity: a profile characteristic (Weapon Skill,
    Initiative), a formation depth (the fighting or supporting ranks). The
    fold is the same shape for all of them, so the result is one neutral
    type, not one per quantity.

    ``factored`` names the rules whose matching modifiers were evaluated
    into the value — including those honoured by not applying (condition
    False). ``unfactored`` names the rules with a matching modifier the
    conditions could not answer (or an unbound parameter); their change
    is *not* in the value, and the caller reports them.

    ``foe_factored`` / ``foe_unfactored`` are the same two lists for the
    *foe's* enemy-subject modifiers ("enemy models suffer a -1 modifier to
    their Strength characteristic"), folded into the same value when the
    caller offers the foe's rules — names of the foe's rules, so the caller
    routes them to the foe's claim set, never the bearer's.
    """

    value: int
    factored: tuple[str, ...] = ()
    unfactored: tuple[str, ...] = ()
    foe_factored: tuple[str, ...] = ()
    foe_unfactored: tuple[str, ...] = ()


def effective_characteristic(
    base: int,
    characteristic: Characteristic,
    rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
    *,
    foe_rules: Sequence[Rule] = (),
    foe_conditions: "GateContext | None" = None,
) -> EffectiveValue:
    """Apply the rules' modifiers to one characteristic read.

    The effective-characteristic query: every read of a characteristic a
    rule can modify goes through here. Scans ``rules`` (a contingent's
    resolved loadout rules) for characteristic modifiers naming
    ``characteristic`` and folds them over ``base`` — each gated on the
    evaluated engagement ``conditions``, each capped by its own printed
    ``maximum`` and floored at its ``minimum``. Rules touching other
    characteristics are not this query's business and appear in neither
    name list.

    ``foe_rules`` are the *other side's* rules, offered where the caller has
    the foe in hand (a combat's two seats): their *enemy-subject* modifiers
    naming ``characteristic`` — "enemy models suffer a -1 modifier to their
    Strength characteristic" — fold into the same value, each gated on the
    bearer's own ``foe_conditions``, their names reported apart
    (``foe_factored`` / ``foe_unfactored``) so the caller claims them for
    the foe. Both sources resolve as one fold, so a foe's enemy-subject set
    cancels the bearer's own disagreeing set exactly as two of the bearer's
    would (Strike First against an aura's Strike Last).

    All-or-nothing per rule, as at compile: if any matching modifier
    needs an unknown fact or an unbound parameter, none of that rule's
    modifiers apply and the rule is reported unfactored.

    Returns:
        The effective value with the factored and unfactored rule names,
        the foe's apart.
    """
    return _effective_quantity(
        base, characteristic, rules, conditions, foe_rules=foe_rules, foe_conditions=foe_conditions
    )


def effective_fighting_ranks(
    base: int,
    rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
) -> EffectiveValue:
    """Apply the rules' modifiers to the number of fighting ranks.

    The fighting-rank query: the sibling of the characteristic query for
    the ``fighting-ranks`` formation quantity. Folds the rank modifiers a
    contingent's rules carry (Press of Battle's +1) over ``base`` — one
    rank by default — under the evaluated ``conditions``, reporting which
    rules were factored and which the facts could not answer.

    Returns:
        The effective depth with the factored and unfactored rule names.
    """
    return _effective_quantity(base, Quantity.FIGHTING_RANKS, rules, conditions)


def effective_supporting_ranks(
    base: int,
    rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
) -> EffectiveValue:
    """Apply the rules' modifiers to the number of supporting ranks.

    The fighting-rank query's twin for the ``supporting-ranks`` formation
    quantity — the ranks behind the fighting rank that support at one attack
    each. Folds the rank modifiers a weapon carries (Fight in Extra Rank's
    +1) over ``base`` — none by default — under the evaluated ``conditions``,
    reporting which rules were factored and which the facts could not answer.

    Returns:
        The effective count with the factored and unfactored rule names.
    """
    return _effective_quantity(base, Quantity.SUPPORTING_RANKS, rules, conditions)


def effective_combat_result_bonus(
    rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
) -> EffectiveValue:
    """Sum the combat-result points a side's rules grant it, bonuses and maluses.

    The generic combat hook: one signed total folded from every
    ``combat-result`` modifier a contingent's rules carry (Massed Infantry's
    +1 when it outnumbers the foe), gated on the evaluated ``conditions``.
    The combat sums this into the round's score without naming what granted
    it — the same shape as the rank folds — so a new bonus or malus is a rule
    in data, not a change here. ``factored`` / ``unfactored`` name the rules
    evaluated in, for the combat notes.

    Returns:
        The signed combat-result total with the factored and unfactored
        rule names.
    """
    return _effective_quantity(0, Quantity.COMBAT_RESULT, rules, conditions)


def effective_armour_value(
    base: int | None,
    rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
) -> EffectiveValue:
    """Improve a defender's armour value by the rules that better its save.

    The armour fold: every ``armour-value`` modifier a contingent's rules
    carry (Parry's +1 with a hand weapon and shield) betters the save by
    lowering the armour value — a lower value is a better save, so an
    improvement subtracts — gated on the ``conditions``, which carry the
    equipment in use (the weapon in hand, the armour worn) beside the engagement
    facts, and floored at the printed ``maximum`` (the best save it may reach).
    All-or-nothing per rule; a rule whose facts the conditions cannot answer is
    reported unfactored.

    ``base`` is None when the defender wears nothing — there is no printed value
    to improve — and the fold still runs, because the rules still need their
    disposition read. One honoured by not applying is factored as ever (Parry
    names a shield, and a model wearing nothing wears none), while one that
    *would* improve the value is reported unfactored rather than applied to a
    base that does not exist. The value returned is then 0, the caller's "no
    save"; this is the seam that owns the question either way, so no armour rule
    goes unspoken for just because its bearer is unarmoured.

    Returns:
        The improved armour value with the factored and unfactored rule names.
    """
    context = _as_context(conditions)
    value = base if base is not None else 0
    factored: list[str] = []
    unfactored: list[str] = []
    for rule in rules:
        matching = [
            (effect, effect.added(Quantity.ARMOUR_VALUE))
            for effect in rule.effects
            if isinstance(effect, ModifierEffect) and Quantity.ARMOUR_VALUE in (effect.add or {})
        ]
        if not matching:
            continue
        answers = [(effect, add, _gate_applies(effect, context)) for effect, add in matching]
        if any(
            add.amount == "X" or when is None or effect.natural is not None
            for effect, add, when in answers
        ):
            unfactored.append(rule.name)
            continue
        if base is None and any(when for _, _, when in answers):
            # Nothing printed to improve: applying it would invent a save out of
            # a value the defender does not have. Reported, never assumed.
            unfactored.append(rule.name)
            continue
        for _, add, when in answers:
            if not when or not isinstance(add.amount, int):
                continue
            value -= add.amount  # a lower armour value is a better save
            if add.maximum is not None:
                value = max(value, add.maximum)  # cannot improve past the best save
        factored.append(rule.name)
        logger.debug("armour-value modifier factored: %s -> %d", rule.name, value)
    return EffectiveValue(value, tuple(factored), tuple(unfactored))


@dataclass(frozen=True)
class BarredWorn:
    """The armour pieces a bearer cannot use, by name, and the rules that bar them."""

    names: frozenset[str] = frozenset()
    factored: tuple[str, ...] = ()


def barred_worn(
    weapon_rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
) -> BarredWorn:
    """The armour pieces the weapon in use bars the bearer from using.

    The consumption of :class:`~avelorn.tow.schema.rule.BarEffect`, run
    where a bearer's usable armour is assembled: a barred piece is withdrawn
    whole — its bonus, whatever its size, and its presence to any gate that
    asks — under the effect's own gate (Requires Two Hands bars the shield
    in close combat and leaves it counting against shooting). All-or-nothing
    per rule, as every fold is; a gate the ``conditions`` cannot answer bars
    nothing and leaves its rule unconsumed, reported rather than guessed.
    A rule *lifting* a bar (an extra limb) has no printed carrier the site
    reaches, so no counter-word exists yet; one joins when an entry needs it.

    Returns:
        The barred piece names and the consumed rule names.
    """
    context = _as_context(conditions)
    names: set[str] = set()
    factored: list[str] = []
    for rule in weapon_rules:
        bars = [effect for effect in rule.effects if isinstance(effect, BarEffect)]
        if not bars:
            continue
        answers = [(effect, _gate_applies(effect, context)) for effect in bars]
        if any(when is None for _, when in answers):
            continue
        names.update(effect.bars for effect, when in answers if when)
        factored.append(rule.name)
    return BarredWorn(frozenset(names), tuple(factored))


@dataclass(frozen=True)
class EffectiveVolley:
    """Whether the rear ranks join the volley, and the rules behind the answer.

    ``fires`` holds when a consumed :class:`~avelorn.tow.schema.rule.VolleyEffect`'s
    gate does; ``factored`` / ``unfactored`` read as on
    :class:`EffectiveValue` — a factored rule includes one honoured with no
    extra shots (the unit moved, or the volley is a Stand & Shoot).
    """

    fires: bool = False
    factored: tuple[str, ...] = ()
    unfactored: tuple[str, ...] = ()


def effective_volley(
    rules: Sequence[Rule], conditions: "GateContext | None" = None
) -> EffectiveVolley:
    """Fold the weapon in use's rules into the volley's rear-rank participation.

    The shot-count sibling of the supporting-rank query: Volley Fire lands
    on how many models fire, never on the dice, so the volley resolver reads
    it here and adds half of each rear rank, rounding up, when it holds.
    All-or-nothing per rule; a gate the ``conditions`` cannot answer is
    reported unfactored.

    Returns:
        The participation with the factored and unfactored rule names.
    """
    context = _as_context(conditions)
    fires = False
    factored: list[str] = []
    unfactored: list[str] = []
    for rule in rules:
        volleys = [effect for effect in rule.effects if isinstance(effect, VolleyEffect)]
        if not volleys:
            continue
        answers = [_gate_applies(effect, context) for effect in volleys]
        if any(answer is None for answer in answers):
            unfactored.append(rule.name)
            continue
        fires = fires or any(answers)
        factored.append(rule.name)
    return EffectiveVolley(fires, tuple(factored), tuple(unfactored))


# The dice a wound multiplier may be printed as, each a uniform die rolled
# separately for each unsaved wound — a distribution, never an expectation.


@dataclass(frozen=True)
class EffectiveWoundMultiplier:
    """The wounds each unsaved wound inflicts, before the model's own cap.

    The wound-multiplier fold's result: ``wounds`` is the distribution of
    wounds one unsaved wound becomes (Multiple Wounds (2) is a certain 2, a
    D3 the uniform die, rolled separately per unsaved wound), or None when
    nothing multiplies — the Remove Casualties fold then pools plain wounds
    as ever. The printed cap at the model's remaining Wounds is that fold's
    to apply, since only it knows the target. ``factored`` / ``unfactored``
    read as on :class:`EffectiveValue`.
    """

    wounds: Distribution[int] | None = None
    factored: tuple[str, ...] = ()
    unfactored: tuple[str, ...] = ()


def effective_wound_multiplier(
    rules: Sequence[Rule], conditions: "GateContext | None" = None
) -> EffectiveWoundMultiplier:
    """Fold the profile in use's rules into the wounds each unsaved wound inflicts.

    The Remove Casualties seam's read, the casualty-side sibling of the
    volley fold: a wound multiplier lands on what an unsaved wound *is
    worth*, never on the dice, so the casualty fold consumes it here rather
    than in the walk. All-or-nothing per rule; a gate the ``conditions``
    cannot answer, or an unbound "X", is reported unfactored.

    Returns:
        The multiplier with the factored and unfactored rule names.

    Raises:
        ValueError: two rules multiply the same attack's wounds — no printed
            rule stacks multipliers, so this is a data error, not a fold.
    """
    context = _as_context(conditions)
    wounds: Distribution[int] | None = None
    factored: list[str] = []
    unfactored: list[str] = []
    for rule in rules:
        matching = [e for e in rule.effects if isinstance(e, WoundMultiplierEffect)]
        if not matching:
            continue
        answers = [(effect, _gate_applies(effect, context)) for effect in matching]
        if any(effect.multiplies == "X" or applies is None for effect, applies in answers):
            unfactored.append(rule.name)
            continue
        for effect, applies in answers:
            if not applies:
                continue
            if wounds is not None:
                raise ValueError(f"{rule.name}: a second wound multiplier applies; none stack")
            wounds = _quantity_distribution(effect.multiplies)
        factored.append(rule.name)
        logger.debug("wound multiplier factored: %s -> %s", rule.name, wounds)
    return EffectiveWoundMultiplier(wounds, tuple(factored), tuple(unfactored))


@dataclass(frozen=True)
class EffectiveHits:
    """The extra automatic hits a contingent's rules land at one point of the round.

    The evaluated half of :class:`~avelorn.tow.schema.rule.HitsEffect` for one
    :class:`~avelorn.tow.schema.rule.HitOrder`: ``per_model`` is the exact
    distribution of hits each model causes — the certainty of 0 when no effect
    holds, a dice quantity folded face by face otherwise. ``factored`` /
    ``unfactored`` read as on :class:`EffectiveValue` — a factored rule
    includes one honoured with no hits (a non-charging bearer of Impact Hits).
    """

    per_model: Distribution[int]
    factored: tuple[str, ...] = ()
    unfactored: tuple[str, ...] = ()


def effective_automatic_hits(
    rules: Sequence[Rule],
    order: HitOrder,
    conditions: "GateContext | None" = None,
) -> EffectiveHits:
    """Fold a contingent's rules into the automatic hits landing at ``order``.

    The automatic-hits seam: every :class:`~avelorn.tow.schema.rule.HitsEffect`
    whose ``order`` matches is gated on the evaluated ``conditions`` (Impact
    Hits' charge of 3" or more), and the holding effects' counts convolve into
    one per-model distribution — a printed number as a certainty, a dice
    quantity uniform over its faces plus the flat addend. All-or-nothing per
    rule, as every fold is; a gate the conditions cannot answer, or an unbound
    "X" parameter, is reported unfactored. A rule whose effects land at the
    *other* order is left for that order's read — neither factored nor
    unfactored here.

    Returns:
        The per-model hit-count distribution with the factored and unfactored
        rule names.
    """
    context = _as_context(conditions)
    per_model: Distribution[int] = Distribution.pure(0)
    factored: list[str] = []
    unfactored: list[str] = []
    for rule in rules:
        matching = [
            effect
            for effect in rule.effects
            if isinstance(effect, HitsEffect) and effect.order is order
        ]
        if not matching:
            continue
        answers = [(effect, _gate_applies(effect, context)) for effect in matching]
        if any(effect.hits == "X" or when is None for effect, when in answers):
            unfactored.append(rule.name)
            continue
        for effect, when in answers:
            if when:
                per_model = per_model + _quantity_distribution(effect.hits)
        factored.append(rule.name)
        logger.debug("automatic hits factored: %s at %s", rule.name, order)
    return EffectiveHits(per_model, tuple(factored), tuple(unfactored))


def _quantity_distribution(hits: "int | DiceQuantity | str") -> Distribution[int]:
    # A printed quantity as its exact distribution: a number is certain, a dice
    # quantity uniform over its faces shifted by the flat addend. The caller
    # guards the unbound "X".
    if isinstance(hits, int):
        return Distribution.pure(hits)
    assert isinstance(hits, DiceQuantity)  # "X" is guarded by the caller
    return Distribution(
        {face + hits.plus: Fraction(1, hits.sides) for face in range(1, hits.sides + 1)}
    )


@dataclass(frozen=True)
class EffectiveMarks:
    """The marks a striker's rules put on the attacks it makes.

    The evaluated half of :class:`~avelorn.tow.schema.rule.AttackMarkEffect`:
    whether the attacks are magical and whether they are Flaming, read from
    the resolved rules of the profile in use and of the unit alike — the
    printed sentences confer either way ("a model with this special rule,
    or ... a weapon with this special rule"). ``weapon_factored`` and
    ``unit_factored`` name the consumed rules per source, so each claims
    its own namespace's note.
    """

    magical: bool = False
    flaming: bool = False
    weapon_factored: tuple[str, ...] = ()
    unit_factored: tuple[str, ...] = ()


def attack_marks(
    profile_rules: Sequence[str],
    weapon_rules: Mapping[str, Rule],
    rules: Sequence[Rule],
) -> EffectiveMarks:
    """Read what the attacks a striker makes *are*: Magical, Flaming.

    The fact producer behind the incoming-attack gates (Lion Cloak's
    non-magical armour bonus, a ward's flame gate): mark effects are
    consumed from the profile in use's resolved entries and from the
    striker's unit rules, and the consumed rule names come back for the
    caller to claim out of the notes. A mark carrying a ``when`` is not
    consumable here — the attack's own facts are what is being built — so
    its rule is left unconsumed and rides noted rather than guessed.

    Returns:
        The marks with the consumed rule names, per source.
    """
    in_use = [weapon_rules[name] for name in profile_rules if name in weapon_rules]
    magical = flaming = False
    weapon_factored: list[str] = []
    unit_factored: list[str] = []
    for source, factored in ((in_use, weapon_factored), (rules, unit_factored)):
        for rule in source:
            marks = [e for e in rule.effects if isinstance(e, AttackMarkEffect)]
            if not marks or any(effect.when is not None for effect in marks):
                continue
            for effect in marks:
                magical = magical or bool(effect.attack.magical)
                flaming = flaming or bool(effect.attack.flaming)
            factored.append(rule.name)
    return EffectiveMarks(magical, flaming, tuple(weapon_factored), tuple(unit_factored))


@dataclass(frozen=True)
class EffectiveWard:
    """The ward save a contingent's rules grant it, if any.

    The ward fold's result. ``target`` is the Warding value the model saves
    on (6 for a printed "6+ Ward save"), or None when nothing grants one —
    unlike a characteristic there is no base to fall back on, so the absent
    case is a real value, not a zero. ``factored`` and ``unfactored`` read as
    on :class:`EffectiveValue`.
    """

    target: int | None
    factored: tuple[str, ...] = ()
    unfactored: tuple[str, ...] = ()


def effective_ward_target(
    rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
) -> EffectiveWard:
    """Fold a defender's rules into the ward save it makes, if any.

    The ward fold, the armour fold's sibling with its own combination rule:
    each ``ward-save`` set a contingent's rules carry (Runes of Protection's
    6+ against non-magical attacks) grants a ward at its printed Warding
    value, gated on the ``conditions`` — the incoming attack's kind and
    magic among them. Wards never stack: where several grants hold, the
    best (lowest) target applies. Armour modifiers never reach it — "rules
    that affect armour values do not affect Warding values"
    (the-shooting-phase/ward-saves) — which is why this is its own seam
    rather than a fold into the armour value. All-or-nothing per rule; a
    rule whose facts the conditions cannot answer is reported unfactored.

    Returns:
        The best granted ward target — None when no grant holds — with the
        factored and unfactored rule names.
    """
    context = _as_context(conditions)
    best: int | None = None
    factored: list[str] = []
    unfactored: list[str] = []
    for rule in rules:
        matching = [
            (effect, (effect.set_ or {})[Quantity.WARD_SAVE])
            for effect in rule.effects
            if isinstance(effect, ModifierEffect) and Quantity.WARD_SAVE in (effect.set_ or {})
        ]
        if not matching:
            continue
        answers = [(effect, amount, _gate_applies(effect, context)) for effect, amount in matching]
        if any(
            amount == "X" or when is None or effect.natural is not None
            for effect, amount, when in answers
        ):
            unfactored.append(rule.name)
            continue
        for _, amount, when in answers:
            if not when or not isinstance(amount, int):
                continue
            best = amount if best is None else min(best, amount)
        factored.append(rule.name)
        logger.debug("ward-save grant factored: %s -> %s", rule.name, best)
    return EffectiveWard(best, tuple(factored), tuple(unfactored))


@dataclass(frozen=True)
class EffectiveRerolls:
    """The re-roll grants a contingent's rules confer on the attack it makes.

    The re-roll seam's fold, the sibling of the armour fold: every attack-roll
    re-roll a rule carries (Ithilmar Weapons' re-roll of To Hit natural 1s),
    gated on the conditions — the engagement facts and the equipment in use
    alike — and compiled into the records the dice walk applies. The name lists
    are the compile's, with the same three meanings (see
    :class:`CompiledRules`): ``factored`` names the rules evaluated in —
    including those honoured by not applying (a gate answered False, the gear it
    names not in use); ``inapplicable`` those whose every grant names the other
    seat's die, which the fold at that seat is the one to own; ``unfactored``
    those a fact could not answer. The caller reports the last, and claims the
    middle one only when it resolves both seats.
    """

    rerolls: tuple[Reroll, ...] = ()
    factored: tuple[str, ...] = ()
    unfactored: tuple[str, ...] = ()
    inapplicable: tuple[str, ...] = ()


def effective_rerolls(
    rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
    *,
    seat: Side = Side.ATTACKER,
) -> EffectiveRerolls:
    """Compile the attack-die re-rolls a contingent's rules grant.

    The re-roll seam: every :class:`RerollEffect` naming a per-attack die (To
    Hit, To Wound, a save) is gated on the ``conditions``, which carry the
    equipment in use beside the engagement facts, exactly as the armour fold
    gates Parry — a rule whose fact the conditions cannot answer is reported
    unfactored, one answered False (the weapon it names not in hand) is honoured
    with no grant. ``seat`` is the side of the attack the rules' bearer occupies
    in the walk being compiled: a grant reaches the walk iff the named stage's
    roller (flipped by the effect's printed ``enemy`` subject) matches it — a
    bearer's own save re-roll joins the attacks it suffers, an enemy-subject
    one the attacks it makes; a rule whose every grant names the other seat is
    inapplicable here, the fold at that seat being the one that owns it.
    Panic-test re-rolls are another seam's and pass untouched.

    Returns:
        The re-roll records the dice walk applies, with each rule's
        disposition (see :class:`EffectiveRerolls`).
    """
    context = _as_context(conditions)
    grants: list[Reroll] = []
    factored: list[str] = []
    unfactored: list[str] = []
    inapplicable: list[str] = []
    for rule in rules:
        matching = [
            effect
            for effect in rule.effects
            if isinstance(effect, RerollEffect) and effect.reroll.dice is Dice.D6_PER_ATTACK
        ]
        if not matching:
            continue
        # The seat gate, before the state gate: a grant whose die belongs to
        # the other seat of this walk (the stage's roller, flipped when the
        # printed subject is the enemy) is no business of this fold whatever
        # its facts say. A rule with nothing else to give is inapplicable
        # here, and grants from its proper seat in the walks where it applies.
        seated = [
            effect
            for effect in matching
            if (effect.reroll.rolled_by.other if effect.enemy else effect.reroll.rolled_by) is seat
        ]
        if not seated:
            inapplicable.append(rule.name)
            continue
        answers = [(effect, _gate_applies(effect, context)) for effect in seated]
        if any(when is None for _, when in answers):
            unfactored.append(rule.name)
            continue
        for effect, when in answers:
            if when:
                grants.append(
                    Reroll(stage=effect.reroll, on_natural=effect.on_natural, of=effect.of)
                )
        factored.append(rule.name)
        logger.debug("re-roll grant factored: %s -> %d record(s)", rule.name, len(grants))
    return EffectiveRerolls(tuple(grants), tuple(factored), tuple(unfactored), tuple(inapplicable))


# One additive operation gathered for the value fold: the amount, and the
# amount's printed maximum (ceiling) and minimum (floor), where the seam caps.
_Add = tuple[int, int | None, int | None]


def _effective_quantity(
    base: int,
    key: Quantity | Characteristic,
    rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
    *,
    foe_rules: Sequence[Rule] = (),
    foe_conditions: "GateContext | None" = None,
) -> EffectiveValue:
    # One base value folded over the ``key`` operations a contingent's rules
    # carry — shared by the characteristic, fighting-rank, and combat-result
    # queries, which differ only in the ``key`` they read. The bearer's own
    # rules contribute their bearer-subject operations; the foe's rules — when
    # the caller has the foe in hand — their *enemy-subject* ones, gated on the
    # foe's own facts and reported apart, into one shared resolution.
    # All-or-nothing per rule; a rule needing an unknown fact, an unbound
    # parameter, or an event face (no die is rolled at a query) is reported
    # unfactored. A printed maximum or minimum bounds only the characteristic
    # seam — the one that prints them — so ranks and combat-result points
    # accumulate unbounded.
    #
    # Two passes, because a `set` replaces the base "before any other
    # modifiers are applied": every applicable set is resolved first, then the
    # additive folds stack on top. Sets that disagree on the target cancel one
    # another (Strike First's 10 against Strike Last's 1) whichever side each
    # came from, leaving the base to stand — each still honoured, just to no
    # effect.
    sets: list[int] = []
    adds: list[_Add] = []
    factored, unfactored = _gather_operations(
        key, rules, _as_context(conditions), enemy=False, sets=sets, adds=adds
    )
    foe_factored, foe_unfactored = _gather_operations(
        key, foe_rules, _as_context(foe_conditions), enemy=True, sets=sets, adds=adds
    )
    value = base
    targets = set(sets)
    if len(targets) == 1:
        value = targets.pop()  # a single agreed target replaces the base
    # no set leaves the base; conflicting sets cancel, and the base stands
    value += sum(amount for amount, _, _ in adds)
    # A printed bound ("to a minimum of 1", "to a maximum of 10") is a property
    # of the modified value, not of one step of the fold — clamping per
    # operation would make the result depend on rule-list order. Every declared
    # bound clamps the finished sum.
    ceilings = [maximum for _, maximum, _ in adds if maximum is not None]
    floors = [minimum for _, _, minimum in adds if minimum is not None]
    if ceilings:
        value = min(value, *ceilings)
    if floors:
        value = max(value, *floors)
    logger.debug("%s -> %d (%d rule(s) factored)", key, value, len(factored) + len(foe_factored))
    return EffectiveValue(value, factored, unfactored, foe_factored, foe_unfactored)


def _gather_operations(
    key: Quantity | Characteristic,
    rules: Sequence[Rule],
    context: GateContext,
    *,
    enemy: bool,
    sets: list[int],
    adds: list[_Add],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    # One source's contribution to a value fold: the ``key`` operations of the
    # given subject (the bearer's own, or — flipped by the printed ``enemy``
    # word — the foe's), gated on that source's own context, gathered into the
    # shared set/add pools. Returns the source's (factored, unfactored) names.
    caps = seam_of(key) is Seam.CHARACTERISTIC
    factored: list[str] = []
    unfactored: list[str] = []
    for rule in rules:
        # A set carries no bound (only an add can), so both read as an ``Add``
        # and the fold below asks one question of either.
        matching: list[tuple[ModifierEffect, str, Add]] = []
        for effect in rule.effects:
            if not isinstance(effect, ModifierEffect) or effect.enemy is not enemy:
                continue
            if key in (effect.add or {}):
                matching.append((effect, "add", effect.added(key)))
            if key in (effect.set_ or {}):
                matching.append((effect, "set", Add((effect.set_ or {})[key])))
        if not matching:
            continue
        answers = [
            (effect, op, add, _gate_applies(effect, context)) for effect, op, add in matching
        ]
        if any(
            add.amount == "X" or answer is None or effect.natural is not None
            for effect, op, add, answer in answers
        ):
            # A rule gated on equipment the caller's conditions do not carry
            # answers None, so it lands here — reported unfactored rather than
            # applied blind, exactly as an unanswerable engagement fact does.
            unfactored.append(rule.name)
            continue
        for _, op, add, answer in answers:
            if not answer or not isinstance(add.amount, int):
                continue
            if op == "set":
                sets.append(add.amount)
            else:
                adds.append(
                    (add.amount, add.maximum if caps else None, add.minimum if caps else None)
                )
        factored.append(rule.name)
    return tuple(factored), tuple(unfactored)


def _gate_applies(effect: GatedEffect, context: GateContext) -> bool | None:
    # A rule's gate holds iff its When tree does, walked against the context.
    # Any gated effect — a modifier or a re-roll grant — reads the same way.
    return True if effect.when is None else _walk(effect.when, context)


def _walk(gate: Gate, facts: object) -> bool | None:
    # Walk a gate model against the mirroring facts object, field by field, and
    # conjoin. None = unknown (a state fact the context could not answer) —
    # reported unfactored by the caller; False = a fact known not to hold —
    # honoured as a no-op; a known-False anywhere settles False amid unknowns.
    # A field the gate leaves unconstrained (None) is skipped, as is the natural
    # die event (not pre-roll state — the dice walk consumes it via
    # effect.natural). Every other constrained field must hook into a same-named
    # fact, or the gate and context shapes have drifted — a loud error.
    outcomes: list[bool | None] = []
    for name, info in type(gate).model_fields.items():
        required = getattr(gate, name)
        if required is None or isinstance(required, NaturalRoll):
            continue
        try:
            actual = getattr(facts, name)
        except AttributeError as err:
            raise TypeError(
                f"{type(gate).__name__}.{name} has no matching fact on "
                f"{type(facts).__name__} — the gate and context shapes have drifted"
            ) from err
        outcomes.append(_node_applies(required, actual, _is_branch(info)))
    if any(outcome is False for outcome in outcomes):
        return False
    if any(outcome is None for outcome in outcomes):
        return None
    return True


def _node_applies(required: object, actual: object, is_branch: bool) -> bool | None:
    # One gate node against its fact. A membership gate (the armour worn): the
    # fact is the collection, and the gate is satisfied by any member matching.
    # A branch (a subject, or an event like the charge or a future incoming
    # attack): a bool requires the entity's presence; a nested gate requires it
    # present and recurses. A leaf: a Comparison tests a number, a bool tests a
    # boolean — both tri-state, so a fact the context could not answer (None)
    # leaves the rule unevaluatable.
    if isinstance(required, MembershipGate):
        return _any_member_applies(required, actual)
    if is_branch:
        if isinstance(required, bool):
            return (actual is not None) == required
        if actual is None:
            return False  # the gate constrains an entity that did not occur
        assert isinstance(required, Gate)  # a branch gate is a nested model
        return _walk(required, actual)
    if isinstance(required, Comparison):
        if actual is None:
            return None
        assert isinstance(actual, int)  # a Comparison leaf reads a numeric fact
        return required.matches(actual)
    if isinstance(required, tuple):
        # A printed list ("infantry or cavalry"): satisfied by any member.
        return None if actual is None else actual in required
    return None if actual is None else (actual == required)


def _any_member_applies(gate: MembershipGate, members: object) -> bool | None:
    # A membership gate against the collection behind it: walk the gate over each
    # member and take the disjunction — "equipped with a shield" holds as soon as
    # one piece worn is a shield. A collection the producer never offered (None)
    # is unknown, so the rule is unevaluatable and reported; an *empty* one is
    # known (the model wears nothing), and settles the gate False. A member the
    # facts left unanswered can only withhold the answer, never supply a match,
    # so an unknown decides only when nothing matched.
    if members is None:
        return None  # the collection was not offered — see GateContext.worn
    assert isinstance(members, tuple)  # a membership fact is a tuple of members
    outcomes = [_walk(gate, member) for member in members]
    if any(outcome is True for outcome in outcomes):
        return True
    if any(outcome is None for outcome in outcomes):
        return None
    return False


def _is_branch(info: FieldInfo) -> bool:
    # A branch slot's gate is a nested Gate — a subject or an event — so its
    # annotation admits a Gate; a leaf slot holds a bool or a Comparison (which
    # is deliberately not a Gate). Read off the schema, so a new subject or
    # entity needs no evaluator change.
    return any(
        isinstance(arg, type) and issubclass(arg, Gate) for arg in get_args(info.annotation)
    )
