"""Roll-target charts from the rulebook.

Sources (tow.whfb.app): the-shooting-phase/roll-to-hit-shooting,
the-shooting-phase/roll-to-wound-shooting, the-shooting-phase/7-to-hit,
the-shooting-phase/determining-armour-value,
the-shooting-phase/armour-piercing,
the-combat-phase/roll-to-hit-combat.
"""

import logging

from avelorn.core.dice import p_d6_at_least

logger = logging.getLogger(__name__)

# Target 7+ resolves as a natural 6 re-rolled at this target; 10+ is impossible.
CONFIRM_TARGETS = {7: 4, 8: 5, 9: 6}

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


def melee_hit_target(weapon_skill: int, target_weapon_skill: int) -> int:
    """Required To Hit roll in close combat, from the WS-vs-WS chart.

    Source: the-combat-phase/roll-to-hit-combat. The printed chart
    cross-references the attacker's Weapon Skill against the target's;
    this reproduces every one of its cells (2+ to 5+):

    - attacker's WS more than double the target's: 2+
    - attacker's WS higher (but not more than double): 3+
    - target's WS more than double the attacker's: 5+
    - otherwise (WS within a factor of two, attacker not ahead): 4+

    Returns:
        The required roll (2..5); a natural 1 always fails and a natural
        6 always hits (both applied at the roll, not the target).
    """
    if weapon_skill > 2 * target_weapon_skill:
        target = 2
    elif weapon_skill > target_weapon_skill:
        target = 3
    elif target_weapon_skill > 2 * weapon_skill:
        target = 5
    else:
        target = 4
    logger.debug(
        "melee to-hit: WS %d vs WS %d -> %s",
        weapon_skill,
        target_weapon_skill,
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
        confirm = CONFIRM_TARGETS.get(target)
        p = 0.0 if confirm is None else (1 / 6) * p_d6_at_least(confirm)
    logger.debug("hit %s -> p=%.3f", _fmt_target(target), p)
    return p


def melee_hit_probability(target: int) -> float:
    """Probability that one close-combat attack hits, given its To Hit target.

    A natural 1 always fails and a natural 6 always hits (regardless of
    modifiers), and there is no 7+ confirmation: a target above 6 still
    hits one time in six (the-combat-phase/roll-to-hit-combat).

    Returns:
        The hit probability, in [1/6, 5/6].
    """
    p = p_d6_at_least(max(target, 2)) if target <= 6 else 1 / 6
    logger.debug("melee hit %s -> p=%.3f", _fmt_target(target), p)
    return p


def wound_probability(target: int | None) -> float:
    """Probability that one wound roll succeeds; a natural 1 always fails.

    "Rolls of a Natural 1" (p.140): a natural 1 on a roll To Wound is a
    fail regardless of modifiers — hence the clamp, even though the
    unmodified chart never produces a target below 2.

    Returns:
        The success probability, or 0.0 when ``target`` is None (the
        chart shows "-": the attack cannot wound).
    """
    p = 0.0 if target is None else p_d6_at_least(max(target, 2))
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
