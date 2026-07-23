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
from typing import assert_never, get_args

from pydantic.fields import FieldInfo

from avelorn.core.registry import Registry, UnknownNameError
from avelorn.tow.engine.attack import Modifier
from avelorn.tow.schema.rule import (
    PARAMETER_SUFFIX,
    Comparison,
    EquipmentUse,
    Gate,
    ModifierEffect,
    NaturalRoll,
    Quantity,
    Rule,
    RuleEffect,
    Seam,
    seam_of,
)
from avelorn.tow.schema.stage import Stage
from avelorn.tow.schema.unit import Characteristic

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
class GateContext:
    """The evaluated facts a gate is tested against, mirroring the When tree.

    One facts object per subject, the peer of the schema's gate models: a
    producer builds one for its phase, filling the facts that phase knows, and
    the evaluator walks an effect's :class:`~avelorn.tow.schema.rule.When`
    against it, subject by subject and property by property. A state fact is
    None when unknown (the tri-state the gate carries); a subject a phase never
    sees keeps its default facts, so a rule gating on it is honoured as
    not-applying rather than left unevaluatable.
    """

    combat: CombatFacts = field(default_factory=CombatFacts)
    movement: MovementFacts = field(default_factory=MovementFacts)
    shooting: ShootingFacts = field(default_factory=ShootingFacts)


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
) -> tuple[list[Modifier], list[str]]:
    """Compile printed rule names into modifier records.

    ``resolved`` maps printed names to their rules as printed — built at
    the muster boundary (a loadout's ``weapon_rules``) or from a registry
    scan; a name absent from it is not modelled. ``conditions`` is the
    evaluated :class:`GateContext` (or None for all-unknown). A rule whose
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
        compiled = _compile(rule, context) if rule is not None else None
        if compiled is None:
            unfactored.append(printed)
        else:
            if compiled:
                logger.debug("rule factored: %s -> %d modifier(s)", printed, len(compiled))
            modifiers.extend(compiled)
    return modifiers, unfactored


def _compile(rule: Rule, context: GateContext) -> list[Modifier] | None:
    # All-or-nothing: every effect must compile, or the rule is
    # unfactored. An effect whose condition evaluates False compiles to
    # no modifiers — honoured, not unfactored.
    if not rule.effects:
        return None
    modifiers: list[Modifier] = []
    for effect in rule.effects:
        compiled = _compile_effect(effect, context)
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


def _compile_effect(effect: RuleEffect, context: GateContext) -> list[Modifier] | None:
    # One effect, top to bottom: bail where the walk cannot honour it,
    # gate on the when's state, then record each additive entry as data —
    # which roll's target moves, by how much, on which natural face.
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
    if effect.requires is not None:
        # The walk has no loadout, so it cannot answer an equipment gate;
        # an equipment-gated effect is honestly unfactored here.
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
    *,
    wielding: str | None,
    worn: Collection[str],
) -> EffectiveValue:
    """Improve a defender's armour value by the rules that better its save.

    The armour fold: every ``armour-value`` modifier a contingent's rules
    carry (Parry's +1 with a hand weapon and shield) betters the save by
    lowering the armour value — a lower value is a better save, so an
    improvement subtracts — gated on the engagement ``conditions`` and the
    equipment each rule ``requires`` in use (``wielding`` the weapon in hand,
    ``worn`` the armour worn), and floored at the printed ``maximum`` (the
    best save it may reach). All-or-nothing per rule; a rule whose facts the
    conditions or the loadout cannot answer is reported unfactored.

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
        answers = [
            (
                effect,
                amount,
                _gate_applies(effect, context),
                _equipment_applies(effect.requirements, wielding, worn),
            )
            for effect, amount in matching
        ]
        if any(
            amount == "X" or when is None or gear is None or effect.natural is not None
            for effect, amount, when, gear in answers
        ):
            unfactored.append(rule.name)
            continue
        for effect, amount, when, gear in answers:
            if not when or not gear or not isinstance(amount, int):
                continue
            value -= amount  # a lower armour value is a better save
            if effect.maximum is not None:
                value = max(value, effect.maximum)  # cannot improve past the best save
        factored.append(rule.name)
        logger.debug("armour-value modifier factored: %s -> %d", rule.name, value)
    return EffectiveValue(value, tuple(factored), tuple(unfactored))


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
            amount == "X" or answer is None or effect.natural is not None or effect.requires
            for effect, op, amount, answer in answers
        ):
            # An equipment gate (``requires``) is not answerable here — only
            # the armour fold carries a loadout — so a rule that needs one is
            # reported unfactored rather than applied blind.
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


def _gate_applies(effect: ModifierEffect, context: GateContext) -> bool | None:
    # A rule's gate holds iff its When tree does, walked against the context.
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
    # One gate node against its fact. A branch (a subject, or an event like the
    # charge or a future incoming attack): a bool requires the entity's
    # presence; a nested gate requires it present and recurses. A leaf: a
    # Comparison tests a number, a bool tests a boolean — both tri-state, so a
    # fact the context could not answer (None) leaves the rule unevaluatable.
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


def _is_branch(info: FieldInfo) -> bool:
    # A branch slot's gate is a nested Gate — a subject or an event — so its
    # annotation admits a Gate; a leaf slot holds a bool or a Comparison (which
    # is deliberately not a Gate). Read off the schema, so a new subject or
    # entity needs no evaluator change.
    return any(
        isinstance(arg, type) and issubclass(arg, Gate) for arg in get_args(info.annotation)
    )


def _equipment_applies(
    requires: Mapping[EquipmentUse, str], wielding: str | None, worn: Collection[str]
) -> bool | None:
    # Conjunction over the equipment a rule needs in use, mirroring
    # _condition_applies: one known mismatch settles "does not apply"; an
    # unknown (nothing armed, so the weapon in hand is undecided) decides only
    # when nothing is known-False. The worn pieces are always known.
    unknown = False
    for use, name in requires.items():
        match use:
            case EquipmentUse.WIELDING:
                if wielding is None:
                    unknown = True
                elif wielding != name:
                    return False
            case EquipmentUse.WORN:
                if name not in worn:
                    return False
            case unhandled:
                assert_never(unhandled)
    return None if unknown else True
