"""The rulebook's dice mechanics as pure functions of plain values.

Shared by both engines; no game objects and no special rules.

Sources (tow.whfb.app): the-shooting-phase/roll-to-hit-shooting,
the-shooting-phase/roll-to-wound-shooting, the-shooting-phase/7-to-hit,
the-shooting-phase/determining-armour-value,
the-shooting-phase/armour-piercing,
the-combat-phase/roll-to-hit-combat.
"""

import logging
from collections.abc import Set
from enum import StrEnum
from fractions import Fraction
from typing import NamedTuple

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

    Note: the "BS 6 or higher" interaction with modifiers is not yet
    modelled; unmodified high BS works (a target of 1 or less simply
    means only a natural 1 fails).

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
    """One die as it lands: its natural face and whether it succeeded.

    ``natural`` is 0 for a roll decided without a die (an automatic or
    impossible roll), which no natural-face rule can name.
    """

    natural: int
    success: bool


class Confirm(StrEnum):
    """How a natural 6 fares against a target above 6."""

    NEVER = "never"  # it fails like every other face
    SECOND_DIE = "second-die"  # the-shooting-phase/7-to-hit
    ALWAYS = "always"  # the-combat-phase/roll-to-hit-combat: a natural 6 always hits


# A target of 7+ under Confirm.SECOND_DIE: the natural 6 confirms at this target; 10+ cannot.
CONFIRM_TARGETS = {7: 4, 8: 5, 9: 6}


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


def success(dice: Distribution[Die]) -> Fraction:
    """The exact probability that a roll succeeds.

    Returns:
        The summed mass of the successful dice.
    """
    return sum((Fraction(p) for die, p in dice.mass.items() if die.success), Fraction(0))


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
