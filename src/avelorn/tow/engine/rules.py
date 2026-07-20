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
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass

from avelorn.core.registry import Registry, UnknownNameError
from avelorn.tow.engine.attack import Modifier
from avelorn.tow.schema.rule import (
    PARAMETER_SUFFIX,
    Condition,
    ModifierEffect,
    ModifierKind,
    RankKind,
    Rule,
    RuleEffect,
)
from avelorn.tow.schema.stage import Stage
from avelorn.tow.schema.unit import Characteristic

logger = logging.getLogger(__name__)

_PARAMETERISED = re.compile(r"^(?P<base>.+) \((?P<value>\d+)\)$")

# The attack sequence's order, for "can this die still shape that roll".
_SEQUENCE = {stage: position for position, stage in enumerate(Stage)}


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
    # effect carries, looking inside mappings (a then's amounts).
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
    conditions: Mapping[Condition, bool | None] | None = None,
) -> tuple[list[Modifier], list[str]]:
    """Compile printed rule names into modifier records.

    ``resolved`` maps printed names to their rules as printed — built at
    the muster boundary (a loadout's ``weapon_rules``) or from a registry
    scan; a name absent from it is not modelled. ``conditions`` are the
    evaluated engagement facts by :class:`Condition`; None means unknown.
    A rule whose condition needs an unknown fact is unfactored and
    reported; a rule whose condition evaluates False is honoured by not
    applying — no modifier, no note.

    Returns:
        The compiled modifier records, and the printed names that could
        not be factored into the math (unresolved, effect-less, or
        carrying an effect the engine cannot honour yet) — the caller
        reports those.
    """
    conditions = conditions or {}
    modifiers: list[Modifier] = []
    unfactored: list[str] = []
    for printed in printed_rules:
        rule = resolved.get(printed)
        compiled = _compile(rule, conditions) if rule is not None else None
        if compiled is None:
            unfactored.append(printed)
        else:
            if compiled:
                logger.debug("rule factored: %s -> %d modifier(s)", printed, len(compiled))
            modifiers.extend(compiled)
    return modifiers, unfactored


def _compile(rule: Rule, conditions: Mapping[Condition, bool | None]) -> list[Modifier] | None:
    # All-or-nothing: every effect must compile, or the rule is
    # unfactored. An effect whose condition evaluates False compiles to
    # no modifiers — honoured, not unfactored.
    if not rule.effects:
        return None
    modifiers: list[Modifier] = []
    for effect in rule.effects:
        compiled = _compile_effect(effect, conditions)
        if compiled is None:
            return None
        modifiers.extend(compiled)
    return modifiers


@dataclass(frozen=True)
class _Roll:
    """The roll a modifier kind changes: where it happens, how its target moves."""

    stage: Stage  # the stage whose roll the kind's quantity decides
    sign: int  # multiplies the printed amount into target movement


# What each modifier kind means, declared once; a drift-guard test keeps
# it covering the whole kind vocabulary. The printed sign conventions
# differ per quantity, and ``sign`` carries them: To Hit modifiers speak
# roll-side (a -1 penalty *raises* the target, so the target moves
# against the amount), Armour Piercing speaks piercing-side (a +1
# improvement worsens the save target by the same amount). What a moved
# target *means* — a 7+ that confirms, a save that cannot be attempted —
# is each roll's own knowledge, in the walk, never stated here.
_ROLLS: Mapping[ModifierKind, _Roll] = {
    "to-hit": _Roll(Stage.ROLL_TO_HIT, sign=-1),
    "armour-piercing": _Roll(Stage.MAKE_ARMOUR_SAVES, sign=+1),
}


def _compile_effect(
    effect: RuleEffect, conditions: Mapping[Condition, bool | None]
) -> list[Modifier] | None:
    # One effect, top to bottom: bail where the walk cannot honour it,
    # gate on the when's state, then record each then entry as data —
    # which roll's target moves, by how much, on which natural face.
    if not isinstance(effect, ModifierEffect):
        # Effects for other seams (e.g. re-rolls on make-panic-tests)
        # are not attack modifiers; their seams consume them directly.
        # As a weapon rule they are honestly unfactored.
        return None
    applies = _condition_applies(effect.conditions, conditions)
    if applies is None:
        return None  # the context cannot answer the condition
    if not applies:
        return []  # honoured: the situation does not arise
    natural = effect.natural
    modifiers: list[Modifier] = []
    for quantity, amount in effect.then.items():
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
class EffectiveCharacteristic:
    """A characteristic read with rule-granted modifiers applied.

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
    conditions: Mapping[Condition, bool | None] | None = None,
) -> EffectiveCharacteristic:
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
    conditions: Mapping[Condition, bool | None] | None = None,
) -> EffectiveCharacteristic:
    """Apply the rules' modifiers to the number of fighting ranks.

    The fighting-rank query: the sibling of the characteristic query for
    the ``fighting-ranks`` formation quantity. Folds the rank modifiers a
    contingent's rules carry (Press of Battle's +1) over ``base`` — one
    rank by default — under the evaluated ``conditions``, reporting which
    rules were factored and which the facts could not answer.

    Returns:
        The effective depth with the factored and unfactored rule names.
    """
    return _effective_quantity(base, "fighting-ranks", rules, conditions)


def effective_supporting_ranks(
    base: int,
    rules: Sequence[Rule],
    conditions: Mapping[Condition, bool | None] | None = None,
) -> EffectiveCharacteristic:
    """Apply the rules' modifiers to the number of supporting ranks.

    The fighting-rank query's twin for the ``supporting-ranks`` formation
    quantity — the ranks behind the fighting rank that support at one attack
    each. Folds the rank modifiers a weapon carries (Fight in Extra Rank's
    +1) over ``base`` — none by default — under the evaluated ``conditions``,
    reporting which rules were factored and which the facts could not answer.

    Returns:
        The effective count with the factored and unfactored rule names.
    """
    return _effective_quantity(base, "supporting-ranks", rules, conditions)


def _effective_quantity(
    base: int,
    key: Characteristic | RankKind,
    rules: Sequence[Rule],
    conditions: Mapping[Condition, bool | None] | None = None,
) -> EffectiveCharacteristic:
    # One base value folded over the ``key`` modifiers a contingent's rules
    # carry — shared by the characteristic and fighting-rank queries, which
    # differ only in the ``then`` key they read. All-or-nothing per rule; a
    # rule needing an unknown fact, an unbound parameter, or an event face
    # (no die is rolled at a query) is reported unfactored.
    conditions = conditions or {}
    value = base
    factored: list[str] = []
    unfactored: list[str] = []
    for rule in rules:
        matching = [
            (effect, effect.then[key])
            for effect in rule.effects
            if isinstance(effect, ModifierEffect) and key in effect.then
        ]
        if not matching:
            continue
        answers = [
            (effect, amount, _condition_applies(effect.conditions, conditions))
            for effect, amount in matching
        ]
        if any(
            amount == "X" or answer is None or effect.natural is not None
            for effect, amount, answer in answers
        ):
            unfactored.append(rule.name)
            continue
        for effect, amount, answer in answers:
            if not answer or not isinstance(amount, int):
                continue
            value += amount
            if effect.maximum is not None:
                value = min(value, effect.maximum)
        factored.append(rule.name)
        logger.debug("%s modifier factored: %s -> %d", key, rule.name, value)
    return EffectiveCharacteristic(value, tuple(factored), tuple(unfactored))


def _condition_applies(
    when: Mapping[Condition, bool] | None, conditions: Mapping[Condition, bool | None]
) -> bool | None:
    # Conjunction over the asked facts: one known-False member settles
    # "does not apply" even if others are unknown; unknown decides only
    # when nothing is known-False.
    if when is None:
        return True
    unknown = False
    for condition, required in when.items():
        actual = conditions.get(condition)
        if actual is None:
            unknown = True
        elif actual != required:
            return False  # definitely does not apply, whatever the unknowns
    return None if unknown else True
