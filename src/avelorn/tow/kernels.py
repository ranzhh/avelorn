"""The rulebook's dice mechanics as pure functions of plain values.

Meant for both engines; legacy calls them today. No game objects and no
special rules.

Sources (tow.whfb.app): the-shooting-phase/roll-to-hit-shooting,
the-shooting-phase/roll-to-wound-shooting, the-shooting-phase/7-to-hit,
the-shooting-phase/bs-of-6-or-higher, the-shooting-phase/to-hit-modifiers,
the-shooting-phase/determining-armour-value,
the-shooting-phase/armour-piercing,
the-combat-phase/roll-to-hit-combat, model-profiles/leadership-tests.
"""

import logging
from collections.abc import Set
from enum import StrEnum
from fractions import Fraction
from itertools import product
from typing import NamedTuple, cast

from avelorn.core.distribution import Distribution

logger = logging.getLogger(__name__)

_FACE = Fraction(1, 6)
_FACES = range(1, 7)

# A model wearing no armour counts as 7+ for modifier purposes; improvements cap at 2+.
UNARMOURED = 7
BEST_ARMOUR_VALUE = 2


def _fmt_target(target: int | None) -> str:
    # Render a roll target the way the rulebook prints it: "5+", or "-" for no roll.
    return f"{target}+" if target is not None else "-"


def shooting_hit_target(ballistic_skill: int, modifier: int = 0) -> int:
    """Required To Hit roll for shooting: 7 minus BS, shifted by modifiers.

    ``modifier`` follows the rulebook's sign convention: penalties are
    negative (e.g. -1 for long range), so they raise the target.

    This is legacy's reading of BS 6 or higher: a target of 1 or less, where
    only a natural 1 fails. :func:`shooting_hit` rolls it as printed.

    Returns:
        The required roll; may exceed 6 (see :func:`hit_probability`).
    """
    target = 7 - ballistic_skill - modifier
    logger.debug(
        "to-hit: BS %d, modifier %d -> %s", ballistic_skill, modifier, _fmt_target(target)
    )
    return target


def melee_hit_target(weapon_skill: int, target_weapon_skill: int, modifier: int = 0) -> int:
    """Required To Hit roll in close combat, from the WS-vs-WS chart.

    Source: the-combat-phase/roll-to-hit-combat. The printed chart
    cross-references the attacker's Weapon Skill against the target's;
    this reproduces every one of its cells (2+ to 5+):

    - attacker's WS more than double the target's: 2+
    - attacker's WS higher (but not more than double): 3+
    - target's WS more than double the attacker's: 5+
    - otherwise (WS within a factor of two, attacker not ahead): 4+

    ``modifier`` follows the rulebook's sign convention: penalties are
    negative, so they raise the target — the same shape as
    :func:`shooting_hit_target`.

    Returns:
        The chart cell (2..5) shifted by modifiers; a natural 1 always
        fails and a natural 6 always hits (both applied at the roll, not
        the target).
    """
    if weapon_skill > 2 * target_weapon_skill:
        chart = 2
    elif weapon_skill > target_weapon_skill:
        chart = 3
    elif target_weapon_skill > 2 * weapon_skill:
        chart = 5
    else:
        chart = 4
    target = chart - modifier
    logger.debug(
        "melee to-hit: WS %d vs WS %d, modifier %d -> %s",
        weapon_skill,
        target_weapon_skill,
        modifier,
        _fmt_target(target),
    )
    return target


def wound_target(strength: int, toughness: int) -> int | None:
    """Required To Wound roll from the Strength vs Toughness chart.

    Returns:
        The required roll (2..6), or None when the chart shows "-"
        (Toughness exceeds Strength by 6 or more: cannot wound).
    """
    difference = toughness - strength
    target = None if difference >= 6 else min(max(4 + difference, 2), 6)
    logger.debug("to-wound: S %d vs T %d -> %s", strength, toughness, _fmt_target(target))
    return target


def armour_save_target(armour_value: int | None, armour_piercing: int = 0) -> int | None:
    """Effective armour save after applying Armour Piercing.

    ``armour_piercing`` follows the printed convention: 0 means "-" (no
    effect) and negative values worsen the save roll, so AP -1 turns a
    5+ save into a 6+.

    Returns:
        The required roll, or None when no save is possible (no armour,
        or the modified target exceeds 6).
    """
    if armour_value is None or armour_value >= UNARMOURED:
        target = None
    else:
        effective = armour_value - armour_piercing
        target = effective if effective <= 6 else None
    logger.debug(
        "armour save: AV %s, AP %d -> %s", armour_value, armour_piercing, _fmt_target(target)
    )
    return target


class Die(NamedTuple):
    """One die as it lands: its natural face and whether it succeeded."""

    natural: int
    success: bool


class Confirm(StrEnum):
    """How a natural 6 fares against a target above 6."""

    NEVER = "never"
    SECOND_DIE = "second-die"
    ALWAYS = "always"


CONFIRM_TARGETS = {7: 4, 8: 5, 9: 6}

HIGH_BALLISTIC_SKILL = {6: 6, 7: 5, 8: 4, 9: 3, 10: 2}


def d6(
    target: int, rerolls: Set[Die] = frozenset(), confirm: Confirm = Confirm.NEVER
) -> Distribution[Die]:
    """Roll one D6 against ``target``, exactly.

    A natural 1 always fails, regardless of modifiers. Above 6, ``confirm``
    says what a natural 6 does. Each die in ``rerolls`` is re-rolled once
    and the fresh die stands as thrown ("no single dice can be re-rolled more
    than once"); a failed confirmation re-rolls the whole die.

    Args:
        target: The modified roll needed; any integer.
        rerolls: The landed dice a re-roll covers, by natural face and result.
        confirm: How a natural 6 fares against a target above 6.

    Returns:
        Each landed die's exact probability.
    """
    throw = _throw(target, confirm)
    return throw.bind(lambda die: throw if die in rerolls else Distribution({die: Fraction(1)}))


def _throw(target: int, confirm: Confirm) -> Distribution[Die]:
    mass: dict[Die, Fraction] = {}
    for face in _FACES:
        if face < 6 or target <= 6 or confirm is Confirm.NEVER:
            landed = [(Die(face, face >= max(target, 2)), _FACE)]
        elif confirm is Confirm.ALWAYS:
            landed = [(Die(6, True), _FACE)]
        elif (second := CONFIRM_TARGETS.get(target)) is None:
            landed = [(Die(6, False), _FACE)]
        else:
            landed = [(Die(6, again >= second), _FACE * _FACE) for again in _FACES]
        for die, p in landed:
            mass[die] = mass.get(die, Fraction(0)) + p
    return Distribution(mass)


def shooting_hit(ballistic_skill: int, modifier: int = 0) -> Distribution[Die]:
    """Roll one shot To Hit, exactly.

    Below Ballistic Skill 6 the roll needs 7 minus BS, shifted by the modifier,
    and a 7+ confirms on a second die. At 6 or higher the first roll needs 2+,
    shifted by the modifier, and a miss is re-rolled against the chart's 6+ to
    2+ with no modifier.

    Returns:
        The die as it lands, the re-roll's when there is one.

    Raises:
        ValueError: BS is off the chart, or a first roll at BS 6 or higher needs
            7+, which the rules do not print.
    """
    if ballistic_skill < 6:
        target = shooting_hit_target(ballistic_skill, modifier)
        return d6(target, confirm=Confirm.SECOND_DIE)
    again = HIGH_BALLISTIC_SKILL.get(ballistic_skill)
    if again is None:
        raise ValueError(f"BS {ballistic_skill} is off the printed chart")
    first = 2 - modifier
    if first > 6:
        raise ValueError(f"BS {ballistic_skill} at {modifier:+d} needs {first}+ on its first roll")
    retry = d6(again)

    def rerolled(die: Die) -> Distribution[Die]:
        return Distribution({die: Fraction(1)}) if die.success else retry

    return d6(first).bind(rerolled)


def success(dice: Distribution[Die]) -> Fraction:
    """The exact probability that a roll succeeds.

    Returns:
        The summed mass of the successful dice.
    """
    return sum((cast(Fraction, p) for die, p in dice.mass.items() if die.success), Fraction(0))


def hit_probability(target: int) -> Fraction:
    """Probability that one shooting attack hits, given its To Hit target.

    A natural 1 always fails; targets of 7+ confirm on a second die
    ("7 to Hit").

    Returns:
        The hit probability, in [0, 5/6], exact.
    """
    p = success(d6(target, confirm=Confirm.SECOND_DIE))
    logger.debug("hit %s -> p=%.3f", _fmt_target(target), p)
    return p


def melee_hit_probability(target: int) -> Fraction:
    """Probability that one close-combat attack hits, given its To Hit target.

    A natural 1 always fails and a natural 6 always hits, with no 7+
    confirmation (the-combat-phase/roll-to-hit-combat).

    Returns:
        The hit probability, in [1/6, 5/6], exact.
    """
    p = success(d6(target, confirm=Confirm.ALWAYS))
    logger.debug("melee hit %s -> p=%.3f", _fmt_target(target), p)
    return p


def wound_probability(target: int | None) -> Fraction:
    """Probability that one wound roll succeeds; a natural 1 always fails.

    Returns:
        The exact success probability, or 0 when ``target`` is None (the
        chart shows "-": the attack cannot wound).
    """
    p = Fraction(0) if target is None else success(d6(target))
    logger.debug("wound %s -> p=%.3f", _fmt_target(target), p)
    return p


def save_probability(target: int | None) -> Fraction:
    """Probability that a save roll succeeds; a natural 1 always fails.

    Returns:
        The exact success probability, or 0 when ``target`` is None (no save).
    """
    p = Fraction(0) if target is None else success(d6(target))
    logger.debug("save %s -> p=%.3f", _fmt_target(target), p)
    return p


def leadership_test(value: int | None, reroll_failed: bool = False) -> Fraction:
    """Exact probability that a 2D6 Leadership test passes.

    Passes on a roll equal to or under ``value``; a natural 12 always fails
    and a natural 2 always passes. A value of 0 or None ("-") fails
    automatically, read the same way as a characteristic test
    (model-profiles/characteristic-tests). A re-rolled failure throws both
    dice again, once, and the second result stands.

    Args:
        value: The Leadership tested against.
        reroll_failed: Whether a failed test is re-rolled.

    Returns:
        P(pass).
    """
    if value is None or value <= 0:
        return Fraction(0)
    passes = sum(
        1
        for first, second in product(_FACES, repeat=2)
        if (roll := first + second) == 2 or (roll != 12 and roll <= value)
    )
    p = Fraction(passes, 36)
    if reroll_failed:
        p = p + (1 - p) * p
    logger.debug("leadership test vs %s, re-roll failed %s -> p=%s", value, reroll_failed, p)
    return p


class Standing(NamedTuple):
    """What is left of a side.

    Attributes:
        models: The models still standing.
        wounds_lost: The Wounds lost by the damaged model.
    """

    models: int
    wounds_lost: int


def remove_casualties(standing: Standing, wounds: int, wounds_per_model: int) -> Standing:
    """Remove casualties for unsaved wounds.

    Wounds land on the damaged model first and carry on to the next once it falls
    (removing-casualties/multiple-wound-models). A side with no models left keeps
    no damaged model.

    Returns:
        The side's standing once the wounds are removed.

    Raises:
        ValueError: ``wounds_per_model`` is below 1, ``wounds`` is negative, or the
            damaged model has lost all its Wounds.
    """
    if wounds_per_model < 1:
        raise ValueError("wounds_per_model must be >= 1")
    if wounds < 0:
        raise ValueError("wounds must be >= 0")
    if standing.wounds_lost >= wounds_per_model:
        raise ValueError(
            f"a damaged model cannot have lost {standing.wounds_lost} of {wounds_per_model} Wounds"
        )
    taken = standing.wounds_lost + wounds
    models = max(standing.models - taken // wounds_per_model, 0)
    return Standing(models, taken % wounds_per_model if models else 0)


class Standings(NamedTuple):
    """What is left of each part of a side, in the side's part order."""

    parts: tuple[tuple[str, Standing], ...]

    @property
    def models(self) -> int:
        """The side's models still standing."""
        return sum(standing.models for _, standing in self.parts)

    @property
    def wounds_lost(self) -> int:
        """The Wounds lost by the side's damaged models."""
        return sum(standing.wounds_lost for _, standing in self.parts)

    def of(self, part: str) -> Standing:
        """One part's standing.

        Returns:
            The part's standing.
        """
        return dict(self.parts)[part]


def back_rank(standings: Standings, wounds: int, order: tuple[tuple[str, int], ...]) -> Standings:
    """Remove casualties part by part in ``order``, each with its Wounds per model.

    Each part takes wounds on its damaged model first, then on its next models,
    until it falls; the wounds left pass to the next part in ``order``
    (removing-casualties/removing-casualties-from-units). Wounds left once every
    part has fallen are lost.

    Returns:
        Each part's standing once the wounds are removed.
    """
    left = dict(standings.parts)
    for part, wounds_per_model in order:
        standing = left[part]
        landed = min(wounds, standing.models * wounds_per_model - standing.wounds_lost)
        left[part] = remove_casualties(standing, landed, wounds_per_model)
        wounds -= landed
    return Standings(tuple((part, left[part]) for part, _ in standings.parts))


def heavy_casualties(models: int, at_start_of_phase: int) -> bool:
    """Check for Heavy Casualties.

    Source: the-psychology-of-war/heavy-casualties.

    Returns:
        True when the unit must take a Panic test.

    Raises:
        ValueError: the unit has more models than at the start of the phase.
    """
    if models > at_start_of_phase:
        raise ValueError(
            f"{models} models exceed the {at_start_of_phase} at the start of the phase"
        )
    return models > 0 and (at_start_of_phase - models) * 4 > at_start_of_phase


def falls_back_in_good_order(models: int, battle_strength: int) -> bool:
    """Check whether a panicked unit falls back in good order.

    Source: the-psychology-of-war/panic-tests.

    Returns:
        True to Fall Back in Good Order, False to Flee.

    Raises:
        ValueError: the unit has more models than its battle strength.
    """
    if models > battle_strength:
        raise ValueError(f"{models} models exceed the battle strength of {battle_strength}")
    return models * 2 > battle_strength
