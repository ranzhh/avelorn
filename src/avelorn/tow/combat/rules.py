"""Compile rule effects into attack transforms.

Printed rule names on units and weapons resolve against the rule
entries under ``data/tow/rules/``; a resolved rule's effects compile
into :class:`~avelorn.tow.combat.attack.Transform`s the dice walk
applies. Resolution honours the convention the rules themselves print:
a bracketed number after the name ("Armour Bane (1)") is the parameter
of the rule filed under the "(X)" placeholder ("the amount shown in
brackets after the name of this special rule").

Compilation is all-or-nothing per rule: if any effect names a stage the
engine does not know, or needs a parameter the printed name did not
supply, the whole rule stays unfactored — reported, never partially or
silently applied. A rule with no effects at all is likewise unfactored:
recognised text the engine cannot yet honour.
"""

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import replace

from avelorn.core.registry import Registry, UnknownNameError
from avelorn.tow.combat.attack import AttackProfile, RollState, Transform
from avelorn.tow.schema.rule import (
    ArmourPiercingEffect,
    Condition,
    Rule,
    RuleEffect,
    ToHitEffect,
)

logger = logging.getLogger(__name__)

_PARAMETERISED = re.compile(r"^(?P<base>.+) \((?P<value>\d+)\)$")
_PARAMETER_PLACEHOLDER = " (X)"


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
            entry = rules.by_name(match.group("base") + _PARAMETER_PLACEHOLDER)
            parameter = int(match.group("value"))
            effects = [_with_parameter(effect, parameter) for effect in entry.effects]
            return entry.model_copy(update={"name": printed, "effects": effects})
    return None


def _with_parameter(effect: RuleEffect, parameter: int) -> RuleEffect:
    # Substitute the printed parameter into every "X" placeholder the
    # effect carries. Introspects the effect's fields, so a new
    # X-bearing kind participates automatically.
    placeholders = {
        name: parameter for name in type(effect).model_fields if getattr(effect, name) == "X"
    }
    return effect.model_copy(update=placeholders) if placeholders else effect


def compile_rules(
    printed_rules: Sequence[str],
    rules: Registry[Rule],
    conditions: Mapping[Condition, bool | None] | None = None,
) -> tuple[list[Transform], list[str]]:
    """Compile printed rule names into transforms.

    ``conditions`` are the evaluated engagement facts by
    :class:`Condition`; None means unknown. A rule whose condition needs
    an unknown fact is unfactored and reported; a rule whose condition
    evaluates False is honoured by not applying — no transform, no note.

    Returns:
        The compiled transforms, and the printed names that could not be
        factored into the math (unresolved, effect-less, or carrying an
        effect the engine cannot honour yet) — the caller reports those.
    """
    conditions = conditions or {}
    transforms: list[Transform] = []
    unfactored: list[str] = []
    for printed in printed_rules:
        rule = printed_rule(printed, rules)
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


def _compile_effect(
    effect: RuleEffect, conditions: Mapping[Condition, bool | None]
) -> list[Transform] | None:
    # Dispatches on the effect kind; grows as kinds join. Every registry
    # stage is hookable today; when the registry outgrows the walk (a
    # named seam the engine does not hook yet), a named-but-unhooked
    # check returns None here — not modelled, not an error.
    match effect:
        case ArmourPiercingEffect():
            if effect.amount == "X" or effect.on_natural is None:
                # An unsubstituted "X" (the printed name carried no
                # parameter), or an unconditional AP change (which belongs
                # on the chart-side AP, not a walk transform).
                return None
            return [
                Transform(
                    stage=effect.stage,
                    on_success=_worsen_save_on_natural(effect.on_natural, effect.amount),
                )
            ]
        case ToHitEffect():
            applies = _condition_applies(effect.when, conditions)
            if applies is None:
                return None  # the context cannot answer the condition
            if not applies:
                return []  # honoured: the situation does not arise
            return [Transform(stage=effect.stage, modify_targets=_shift_hit(effect.amount))]
        case _:
            # Effects for other seams (e.g. re-rolls on make-panic-tests)
            # are not attack transforms; their seams consume them
            # directly. As a weapon rule they are honestly unfactored.
            return None


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


def _shift_hit(amount: int) -> Callable[[AttackProfile], AttackProfile]:
    # Printed sign convention: a -1 To Hit modifier raises the target by 1.
    def apply(profile: AttackProfile) -> AttackProfile:
        if not isinstance(profile.hit_target, int):
            return profile
        return replace(profile, hit_target=profile.hit_target - amount)

    return apply


def _worsen_save_on_natural(
    natural: int, amount: int
) -> Callable[[int, AttackProfile], AttackProfile]:
    # Armour Piercing improves by ``amount``: the save target worsens by
    # the same amount, and past 6+ there is no save at all.
    def apply(face: int, profile: AttackProfile) -> AttackProfile:
        if face != natural or not isinstance(profile.save_target, int):
            return profile
        worsened = profile.save_target + amount
        return replace(profile, save_target=worsened if worsened <= 6 else RollState.IMPOSSIBLE)

    return apply
