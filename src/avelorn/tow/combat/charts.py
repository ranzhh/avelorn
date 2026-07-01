"""Roll-target charts from the rulebook.

Sources (tow.whfb.app): the-shooting-phase/roll-to-hit-shooting,
the-shooting-phase/roll-to-wound-shooting, the-shooting-phase/7-to-hit,
the-shooting-phase/determining-armour-value,
the-shooting-phase/armour-piercing.
"""

import logging

from avelorn.core.dice import p_d6_at_least

logger = logging.getLogger(__name__)

# Target 7+ resolves as a natural 6 re-rolled at this target; 10+ is impossible.
_CONFIRM_TARGETS = {7: 4, 8: 5, 9: 6}

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


def hit_probability(target: int) -> float:
    """Probability that one shooting attack hits, given its To Hit target.

    Encodes two rulebook rules: a natural 1 always fails (so targets of
    1 or less still fail one time in six), and targets of 7+ resolve as
    a natural 6 re-rolled (7: 4+, 8: 5+, 9: 6; 10+ impossible).

    Returns:
        The hit probability, in [0.0, 5/6].
    """
    if target <= 6:
        p = p_d6_at_least(max(target, 2))
    else:
        confirm = _CONFIRM_TARGETS.get(target)
        p = 0.0 if confirm is None else (1 / 6) * p_d6_at_least(confirm)
    logger.debug("hit %s -> p=%.3f", _fmt_target(target), p)
    return p


def wound_probability(target: int | None) -> float:
    """Probability that one wound roll succeeds; a natural 1 always fails.

    Returns:
        The success probability, or 0.0 when ``target`` is None (the
        chart shows "-": the attack cannot wound).
    """
    p = 0.0 if target is None else p_d6_at_least(target)
    logger.debug("wound %s -> p=%.3f", _fmt_target(target), p)
    return p


def save_probability(target: int | None) -> float:
    """Probability that a save roll succeeds; a natural 1 always fails.

    Returns:
        The success probability, or 0.0 when ``target`` is None (no save).
    """
    p = 0.0 if target is None else p_d6_at_least(max(target, 2))
    logger.debug("save %s -> p=%.3f", _fmt_target(target), p)
    return p
