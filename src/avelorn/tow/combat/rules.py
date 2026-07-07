"""Compile rule effects into attack transforms.

Printed rule names on units and weapons resolve against the rule
entries under ``data/tow/rules/``; a resolved rule's effects compile
into :class:`~avelorn.tow.combat.attack.Transform`s the dice walk
applies. Resolution honours the convention the rules themselves print:
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
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass

from avelorn.core.registry import Registry, UnknownNameError
from avelorn.tow.combat.attack import AttackProfile, Transform
from avelorn.tow.schema.rule import (
    PARAMETER_SUFFIX,
    Condition,
    ModifierEffect,
    ModifierKind,
    Rule,
    RuleEffect,
)
from avelorn.tow.schema.stage import Stage

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
) -> tuple[list[Transform], list[str]]:
    """Compile printed rule names into transforms.

    ``resolved`` maps printed names to their rules as printed — built at
    the muster boundary (a loadout's ``weapon_rules``) or from a registry
    scan; a name absent from it is not modelled. ``conditions`` are the
    evaluated engagement facts by :class:`Condition`; None means unknown.
    A rule whose condition needs an unknown fact is unfactored and
    reported; a rule whose condition evaluates False is honoured by not
    applying — no transform, no note.

    Returns:
        The compiled transforms, and the printed names that could not be
        factored into the math (unresolved, effect-less, or carrying an
        effect the engine cannot honour yet) — the caller reports those.
    """
    conditions = conditions or {}
    transforms: list[Transform] = []
    unfactored: list[str] = []
    for printed in printed_rules:
        rule = resolved.get(printed)
        compiled = _compile(rule, conditions) if rule is not None else None
        if compiled is None:
            unfactored.append(printed)
        else:
            if compiled:
                logger.debug("rule factored: %s -> %d transform(s)", printed, len(compiled))
            transforms.extend(compiled)
    return transforms, unfactored


def _compile(rule: Rule, conditions: Mapping[Condition, bool | None]) -> list[Transform] | None:
    # All-or-nothing: every effect must compile, or the rule is
    # unfactored. An effect whose condition evaluates False compiles to
    # no transforms — honoured, not unfactored.
    if not rule.effects:
        return None
    transforms: list[Transform] = []
    for effect in rule.effects:
        compiled = _compile_effect(effect, conditions)
        if compiled is None:
            return None
        transforms.extend(compiled)
    return transforms


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
) -> list[Transform] | None:
    # One effect, top to bottom: bail where the walk cannot honour it,
    # gate on the when's state, then hook each then entry's changed
    # roll — before its own roll, or on the natural die when the when
    # names one.
    if not isinstance(effect, ModifierEffect):
        # Effects for other seams (e.g. re-rolls on make-panic-tests)
        # are not attack transforms; their seams consume them directly.
        # As a weapon rule they are honestly unfactored.
        return None
    applies = _condition_applies(effect.conditions, conditions)
    if applies is None:
        return None  # the context cannot answer the condition
    if not applies:
        return []  # honoured: the situation does not arise
    natural = effect.natural
    transforms: list[Transform] = []
    for quantity, amount in effect.then.items():
        if amount == "X":
            # Unsubstituted placeholder: the printed name carried no parameter.
            return None
        roll = _ROLLS[quantity]
        change = _move_target(roll, amount)
        if natural is None:
            transforms.append(Transform(stage=roll.stage, modify_targets=change))
            continue
        if _SEQUENCE[natural.roll] >= _SEQUENCE[roll.stage]:
            # A die can only shape rolls still to come; an event at or
            # after the changed roll cannot be honoured.
            return None
        transforms.append(
            Transform(stage=natural.roll, on_success=_when_natural(natural.face, change))
        )
    return transforms


def _move_target(roll: _Roll, amount: int) -> Callable[[AttackProfile], AttackProfile]:
    # The one profile change every modifier kind shares: move the roll's
    # target by the printed amount under the kind's sign convention. A
    # target that is no die (a RollState) has nothing to move.
    def change(profile: AttackProfile) -> AttackProfile:
        target = profile.target(roll.stage)
        if not isinstance(target, int):
            return profile
        return profile.with_target(roll.stage, target + roll.sign * amount)

    return change


def _when_natural(
    face: int, change: Callable[[AttackProfile], AttackProfile]
) -> Callable[[int, AttackProfile], AttackProfile]:
    # Fire the change only when the trigger stage's die shows the
    # natural face; the walk hands the face to on_success hooks.
    def on_success(rolled: int, profile: AttackProfile) -> AttackProfile:
        return change(profile) if rolled == face else profile

    return on_success


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
