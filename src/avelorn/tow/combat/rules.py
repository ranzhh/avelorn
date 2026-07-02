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
from dataclasses import dataclass, replace

from avelorn.tow.combat.attack import AttackProfile, RollState, Transform
from avelorn.tow.schema.rule import ArmourPiercingEffect, Rule, RuleEffect

logger = logging.getLogger(__name__)

_PARAMETERISED = re.compile(r"^(?P<base>.+) \((?P<value>\d+)\)$")
_PARAMETER_PLACEHOLDER = " (X)"


@dataclass(frozen=True)
class ResolvedRule:
    """A printed rule name matched to its rule entry."""

    rule: Rule
    parameter: int | None  # the bracketed number, e.g. 1 for "Armour Bane (1)"


def resolve_rule(printed: str, rules: Mapping[str, Rule]) -> ResolvedRule | None:
    """Match a printed rule name against a registry keyed by rule name.

    An exact name match wins; otherwise a bracketed numeric parameter
    matches the rule named with the "(X)" placeholder.

    Returns:
        The resolved rule and its parameter, or None if nothing matches.
    """
    rule = rules.get(printed)
    if rule is not None:
        return ResolvedRule(rule=rule, parameter=None)
    if match := _PARAMETERISED.match(printed):
        rule = rules.get(match.group("base") + _PARAMETER_PLACEHOLDER)
        if rule is not None:
            return ResolvedRule(rule=rule, parameter=int(match.group("value")))
    return None


def compile_rules(
    printed_rules: Sequence[str], rules: Mapping[str, Rule]
) -> tuple[list[Transform], list[str]]:
    """Compile printed rule names into transforms.

    Returns:
        The compiled transforms, and the printed names that could not be
        factored into the math (unresolved, effect-less, or carrying an
        effect the engine cannot honour yet) — the caller reports those.
    """
    transforms: list[Transform] = []
    unfactored: list[str] = []
    for printed in printed_rules:
        resolved = resolve_rule(printed, rules)
        compiled = _compile(resolved) if resolved is not None else None
        if compiled:
            logger.debug("rule factored: %s -> %d transform(s)", printed, len(compiled))
            transforms.extend(compiled)
        else:
            unfactored.append(printed)
    return transforms, unfactored


def _compile(resolved: ResolvedRule) -> list[Transform] | None:
    # All-or-nothing: every effect must compile, or the rule is unfactored.
    transforms = []
    for effect in resolved.rule.effects:
        transform = _compile_effect(effect, resolved.parameter)
        if transform is None:
            return None
        transforms.append(transform)
    return transforms or None


def _compile_effect(effect: RuleEffect, parameter: int | None) -> Transform | None:
    # Dispatches on the effect kind; grows as kinds join. Every registry
    # stage is hookable today; when the registry outgrows the walk (a
    # named seam the engine does not hook yet), a named-but-unhooked
    # check returns None here — not modelled, not an error.
    match effect:
        case ArmourPiercingEffect():
            amount = parameter if effect.amount == "X" else effect.amount
            if amount is None or effect.on_natural is None:
                # "X" without a printed parameter, or an unconditional AP
                # change (which belongs on the chart-side AP, not a walk
                # transform).
                return None
            return Transform(
                stage=effect.stage,
                on_success=_worsen_save_on_natural(effect.on_natural, amount),
            )
        case _:
            # to-hit effects condition on the engagement context, which the
            # compiler does not receive yet — inert until it does.
            return None


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
