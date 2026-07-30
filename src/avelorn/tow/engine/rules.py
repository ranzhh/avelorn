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
"""

import logging
import re
from collections.abc import Collection, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from typing import get_args

from pydantic.fields import FieldInfo

from avelorn.core.registry import Registry, UnknownNameError
from avelorn.tow.engine.attack import Modifier, Reroll
from avelorn.tow.schema.psychology import Outcome
from avelorn.tow.schema.rule import (
    PARAMETER_SUFFIX,
    AttackKind,
    ChoiceEffect,
    Comparison,
    Decision,
    Gate,
    GatedEffect,
    GrantEffect,
    MembershipGate,
    ModifierEffect,
    NaturalRoll,
    Quantity,
    RerollEffect,
    Rule,
    RuleEffect,
    Seam,
    seam_of,
)
from avelorn.tow.schema.stage import ATTACK_ROLLS, Stage
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.schema.weapon import WeaponType

logger = logging.getLogger(__name__)

_PARAMETERISED = re.compile(r"^(?P<base>.+) \((?P<value>\d+)\)$")

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
class AttackFacts:
    """The evaluated facts of the incoming attack — the values behind an AttackGate."""

    kind: AttackKind | None = None
    magical: bool | None = None


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
            parameter = int(match.group("value"))
            effects = [_with_parameter(effect, parameter) for effect in entry.effects]
            return entry.model_copy(update={"name": printed, "effects": effects})
    return None


def _with_parameter(effect: RuleEffect, parameter: int) -> RuleEffect:
    # Substitute the printed parameter into every "X" placeholder the
    # effect carries, looking inside mappings (an operation's amounts).
    # Introspects the effect's fields, so a new X-bearing field
    # participates automatically.
    placeholders: dict = {}
    for name in type(effect).model_fields:
        value = getattr(effect, name)
        if value == "X":
            placeholders[name] = parameter
        elif isinstance(value, Mapping) and "X" in value.values():
            placeholders[name] = {
                key: parameter if amount == "X" else amount for key, amount in value.items()
            }
    return effect.model_copy(update=placeholders) if placeholders else effect


def compile_rules(
    printed_rules: Sequence[str],
    resolved: Mapping[str, Rule],
    conditions: "GateContext | None" = None,
    *,
    grants: "Mapping[str, Rule] | None" = None,
) -> tuple[list[Modifier], list[str]]:
    """Compile printed rule names into modifier records.

    ``resolved`` maps printed names to their rules as printed — built at
    the muster boundary (a loadout's ``weapon_rules``) or from a registry
    scan; a name absent from it is not modelled. ``conditions`` is the
    evaluated :class:`GateContext` (or None for all-unknown). ``grants`` maps
    the printed names of rules *conferred* by a grant effect to their resolved
    entries (a loadout's ``granted_rules``) — the lookup a
    :class:`~avelorn.tow.schema.rule.GrantEffect` expands through; a granted
    name absent from it is unfactored, like any unmodelled rule. A rule whose
    gate needs an unknown fact is unfactored and reported; a rule whose gate
    evaluates False is honoured by not applying — no modifier, no note.

    Returns:
        The compiled modifier records, and the printed names that could
        not be factored into the math (unresolved, effect-less, or
        carrying an effect the engine cannot honour yet) — the caller
        reports those.
    """
    context = _as_context(conditions)
    modifiers: list[Modifier] = []
    unfactored: list[str] = []
    for printed in printed_rules:
        rule = resolved.get(printed)
        compiled = _compile(rule, context, grants) if rule is not None else None
        if compiled is None:
            unfactored.append(printed)
        else:
            if compiled:
                logger.debug("rule factored: %s -> %d modifier(s)", printed, len(compiled))
            modifiers.extend(compiled)
    return modifiers, unfactored


def factored_notes(rules: Sequence[Rule], factored: Collection[str], source: str) -> list[str]:
    """The authored ``notes`` of the factored rules that carry them.

    A rule's hand-authored :attr:`~avelorn.tow.schema.rule.Rule.notes` (its
    modelling scope) surface wherever the rule was factored, labelled by rule
    and ``source`` (the unit) — the generic relay every seam shares, so a
    caveat is stated in the rule's data and shown beside the figure it
    qualifies, never composed as prose in the engine.

    Returns:
        One note per factored rule that authored some, for a result's notes.
    """
    return [
        f"{rule.name} ({source}): {rule.notes}"
        for rule in rules
        if rule.name in factored and rule.notes
    ]


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


def _compile(
    rule: Rule, context: GateContext, grants: "Mapping[str, Rule] | None" = None
) -> list[Modifier] | None:
    # All-or-nothing: every effect must compile, or the rule is
    # unfactored. An effect whose condition evaluates False compiles to
    # no modifiers — honoured, not unfactored.
    if not rule.effects:
        return None
    modifiers: list[Modifier] = []
    for effect in rule.effects:
        compiled = _compile_effect(effect, context, grants)
        if compiled is None:
            return None
        modifiers.extend(compiled)
    return modifiers


@dataclass(frozen=True)
class _Roll:
    """The roll a modifier kind changes: where it happens, how its target moves."""

    stage: Stage  # the stage whose roll the kind's quantity decides
    sign: int  # multiplies the printed amount into target movement


# What each roll-seam quantity means, declared once; a drift-guard test keeps
# it covering every roll-seam Quantity. The printed sign conventions differ
# per quantity, and ``sign`` carries them: To Hit modifiers speak roll-side
# (a -1 penalty *raises* the target, so the target moves against the amount),
# Armour Piercing speaks piercing-side (a +1 improvement worsens the save
# target by the same amount). What a moved target *means* — a 7+ that
# confirms, a save that cannot be attempted — is each roll's own knowledge,
# in the walk, never stated here.
_ROLLS: Mapping[Quantity, _Roll] = {
    Quantity.TO_HIT: _Roll(Stage.ROLL_TO_HIT, sign=-1),
    Quantity.ARMOUR_PIERCING: _Roll(Stage.MAKE_ARMOUR_SAVES, sign=+1),
}


def _compile_effect(
    effect: RuleEffect, context: GateContext, grants: "Mapping[str, Rule] | None" = None
) -> list[Modifier] | None:
    # One effect, top to bottom: bail where the walk cannot honour it,
    # gate on the when's state, then record each additive entry as data —
    # which roll's target moves, by how much, on which natural face.
    if isinstance(effect, GrantEffect):
        # A grant confers a named rule under its own outer gate; the granted
        # rule's own effects (kept with their inner gates) compile in its place.
        return _compile_grant(effect, context, grants)
    if not isinstance(effect, ModifierEffect):
        # Effects for other seams (e.g. re-rolls on make-panic-tests)
        # are not attack modifiers; their seams consume them directly.
        # As a weapon rule they are honestly unfactored.
        return None
    if effect.set_:
        # A set replaces a base value, which the effective-value query reads,
        # not the walk (the walk only moves a roll's target). A set on a roll
        # quantity is rejected at load, so any set reaching here belongs to
        # another seam — unfactored, exactly as the characteristic and rank
        # adds below are. None is this compiler's "unfactored" signal (turned
        # into a visible "not factored" note by compile_rules), never an error.
        return None
    applies = _gate_applies(effect, context)
    if applies is None:
        return None  # the context cannot answer the condition
    if not applies:
        return []  # honoured: the situation does not arise
    natural = effect.natural
    modifiers: list[Modifier] = []
    for quantity, amount in (effect.add or {}).items():
        if amount == "X":
            # Unsubstituted placeholder: the printed name carried no parameter.
            return None
        if quantity not in _ROLLS:
            # The walk handles only roll quantities (the _ROLLS vocabulary).
            # A characteristic is the effective-characteristic query's, a rank
            # quantity the fighting-rank query's; as a weapon or phase rule
            # here they are honestly unfactored.
            return None
        roll = _ROLLS[quantity]
        if natural is not None and _SEQUENCE[natural.roll] >= _SEQUENCE[roll.stage]:
            # A die can only shape rolls still to come; an event at or
            # after the changed roll cannot be honoured.
            return None
        modifiers.append(Modifier(lands_on=roll.stage, move=roll.sign * amount, trigger=natural))
    return modifiers


def _compile_grant(
    effect: GrantEffect, context: GateContext, grants: "Mapping[str, Rule] | None"
) -> list[Modifier] | None:
    # A grant confers a named rule under its own *outer* gate: evaluate that gate,
    # then — when it holds — compile the granted rule in its place, its own
    # effects keeping their *inner* gates (Armour Bane's natural-6 To Wound). The
    # two gates conjoin without merging the trees. The grant stacks with any
    # instance the model already carries, because each is compiled independently.
    applies = _gate_applies(effect, context)
    if applies is None:
        return None  # the context cannot answer the grant's gate
    if not applies:
        return []  # honoured: the grant does not fire
    granted = (grants or {}).get(effect.grants)
    if granted is None:
        return None  # the granted rule is not resolvable/modelled — unfactored
    return _compile(granted, context, grants)


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
    """

    value: int
    factored: tuple[str, ...] = ()
    unfactored: tuple[str, ...] = ()


def effective_characteristic(
    base: int,
    characteristic: Characteristic,
    rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
) -> EffectiveValue:
    """Apply the rules' modifiers to one characteristic read.

    The effective-characteristic query: every read of a characteristic a
    rule can modify goes through here. Scans ``rules`` (a contingent's
    resolved loadout rules) for characteristic modifiers naming
    ``characteristic`` and folds them over ``base`` — each gated on the
    evaluated engagement ``conditions``, each capped by its own printed
    ``maximum``. Rules touching other characteristics are not this
    query's business and appear in neither name list.

    All-or-nothing per rule, as at compile: if any matching modifier
    needs an unknown fact or an unbound parameter, none of that rule's
    modifiers apply and the rule is reported unfactored.

    Returns:
        The effective value with the factored and unfactored rule names.
    """
    return _effective_quantity(base, characteristic, rules, conditions)


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
    base: int,
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

    Returns:
        The improved armour value with the factored and unfactored rule names.
    """
    context = _as_context(conditions)
    value = base
    factored: list[str] = []
    unfactored: list[str] = []
    for rule in rules:
        matching = [
            (effect, (effect.add or {})[Quantity.ARMOUR_VALUE])
            for effect in rule.effects
            if isinstance(effect, ModifierEffect) and Quantity.ARMOUR_VALUE in (effect.add or {})
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
        for effect, amount, when in answers:
            if not when or not isinstance(amount, int):
                continue
            value -= amount  # a lower armour value is a better save
            if effect.maximum is not None:
                value = max(value, effect.maximum)  # cannot improve past the best save
        factored.append(rule.name)
        logger.debug("armour-value modifier factored: %s -> %d", rule.name, value)
    return EffectiveValue(value, tuple(factored), tuple(unfactored))


@dataclass(frozen=True)
class EffectiveRerolls:
    """The re-roll grants a contingent's rules confer on the attack it makes.

    The re-roll seam's fold, the sibling of the armour fold: every attack-roll
    re-roll a rule carries (Ithilmar Weapons' re-roll of To Hit natural 1s),
    gated on the conditions — the engagement facts and the equipment in use
    alike — and compiled into the records the dice walk applies. ``factored``
    names the rules evaluated in — including those honoured by not applying (a
    gate answered False, the gear it names not in use) — and ``unfactored`` those
    a fact could not answer; the caller reports the latter.
    """

    rerolls: tuple[Reroll, ...] = ()
    factored: tuple[str, ...] = ()
    unfactored: tuple[str, ...] = ()


def effective_rerolls(
    rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
    *,
    stages: Collection[Stage] = ATTACK_ROLLS,
) -> EffectiveRerolls:
    """Compile the re-rolls a contingent's rules grant at ``stages``.

    The re-roll seam: every :class:`RerollEffect` naming one of ``stages`` is
    gated on the ``conditions``, which carry the equipment in use beside the
    engagement facts, exactly as the armour fold gates Parry — a rule whose
    fact the conditions cannot answer is reported unfactored, one answered
    False (the weapon it names not in hand) is honoured with no grant.

    ``stages`` is how a caller asks for its own dice: a striker reads
    :data:`~avelorn.tow.schema.stage.ATTACKER_ATTACK_ROLLS`, the model saving
    reads :data:`~avelorn.tow.schema.stage.DEFENDER_ATTACK_ROLLS`. A re-roll
    naming a stage outside them belongs to another seam and passes untouched,
    neither factored nor reported — the way a panic-test re-roll always has.

    Returns:
        The re-roll records the dice walk applies, with factored and
        unfactored rule names.
    """
    context = _as_context(conditions)
    grants: list[Reroll] = []
    factored: list[str] = []
    unfactored: list[str] = []
    for rule in rules:
        matching = [
            effect
            for effect in rule.effects
            if isinstance(effect, RerollEffect) and effect.reroll in stages
        ]
        if not matching:
            continue
        answers = [(effect, _gate_applies(effect, context)) for effect in matching]
        if any(when is None for _, when in answers):
            unfactored.append(rule.name)
            continue
        for effect, when in answers:
            if when:
                grants.append(Reroll(stage=effect.reroll, on_natural=effect.on_natural))
        factored.append(rule.name)
        logger.debug("re-roll grant factored: %s -> %d record(s)", rule.name, len(grants))
    return EffectiveRerolls(tuple(grants), tuple(factored), tuple(unfactored))


def _effective_quantity(
    base: int,
    key: Quantity | Characteristic,
    rules: Sequence[Rule],
    conditions: "GateContext | None" = None,
) -> EffectiveValue:
    # One base value folded over the ``key`` operations a contingent's rules
    # carry — shared by the characteristic, fighting-rank, and combat-result
    # queries, which differ only in the ``key`` they read. All-or-nothing
    # per rule; a rule needing an unknown fact, an unbound parameter, or an
    # event face (no die is rolled at a query) is reported unfactored. A
    # printed maximum caps only the characteristic seam — the one that prints
    # one — so ranks and combat-result points accumulate uncapped.
    #
    # Two passes, because a `set` replaces the base "before any other
    # modifiers are applied": every applicable set is resolved first, then the
    # additive folds stack on top. Sets that disagree on the target cancel one
    # another (Strike First's 10 against Strike Last's 1), leaving the base to
    # stand — each still honoured, just to no effect.
    context = _as_context(conditions)
    caps = seam_of(key) is Seam.CHARACTERISTIC
    factored: list[str] = []
    unfactored: list[str] = []
    sets: list[int] = []
    adds: list[tuple[int, int | None]] = []  # (amount, the effect's printed maximum)
    for rule in rules:
        matching = [
            (effect, op, operations[key])
            for effect in rule.effects
            if isinstance(effect, ModifierEffect)
            for op, operations in (("add", effect.add or {}), ("set", effect.set_ or {}))
            if key in operations
        ]
        if not matching:
            continue
        answers = [
            (effect, op, amount, _gate_applies(effect, context)) for effect, op, amount in matching
        ]
        if any(
            amount == "X" or answer is None or effect.natural is not None
            for effect, op, amount, answer in answers
        ):
            # A rule gated on equipment the caller's conditions do not carry
            # answers None, so it lands here — reported unfactored rather than
            # applied blind, exactly as an unanswerable engagement fact does.
            unfactored.append(rule.name)
            continue
        for effect, op, amount, answer in answers:
            if not answer or not isinstance(amount, int):
                continue
            if op == "set":
                sets.append(amount)
            else:
                adds.append((amount, effect.maximum if caps else None))
        factored.append(rule.name)
    value = base
    targets = set(sets)
    if len(targets) == 1:
        value = targets.pop()  # a single agreed target replaces the base
    # no set leaves the base; conflicting sets cancel, and the base stands
    for amount, maximum in adds:
        value += amount
        if maximum is not None:
            value = min(value, maximum)
    logger.debug("%s -> %d (%d rule(s) factored)", key, value, len(factored))
    return EffectiveValue(value, tuple(factored), tuple(unfactored))


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
