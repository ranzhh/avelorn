"""Exact resolution of a single attack as a walk over its dice.

Stage names come verbatim from the printed shooting-phase sequence
(tow.whfb.app/the-shooting-phase): Roll to Hit, Roll to Wound, Make
Armour Saves, Ward Saves. The walk enumerates every die face branch by
branch — including the 7+ to Hit confirmation roll — so later increments
can hook rules onto individual stages and dice ("on a natural 6 To
Wound" needs the die, not just its probability). Today its only output
is the unsaved-wound probability, exactly matching the scalar chain it
replaces; probabilities are exact fractions, converted to float at the
caller's edge.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from avelorn.tow.combat.charts import CONFIRM_TARGETS

logger = logging.getLogger(__name__)

_FACE = Fraction(1, 6)
_FACES = range(1, 7)


class Stage(StrEnum):
    """The attack sequence's stages, named as the rulebook prints them."""

    ROLL_TO_HIT = "roll-to-hit"
    ROLL_TO_WOUND = "roll-to-wound"
    MAKE_ARMOUR_SAVES = "make-armour-saves"
    WARD_SAVES = "ward-saves"


@dataclass(frozen=True)
class AttackProfile:
    """Roll targets for one attack, as produced by the charts."""

    hit_target: int
    wound_target: int | None
    save_target: int | None
    ward_target: int | None


@dataclass(frozen=True)
class AttackResolution:
    """Exact outcome probabilities of a single attack."""

    p_unsaved: Fraction


def resolve_attack(profile: AttackProfile) -> AttackResolution:
    """Resolve one attack by walking its dice exactly.

    Returns:
        The exact per-attack outcome probabilities; today just the
        unsaved wound.
    """
    unsaved = sum(
        (p_path for p_path, wound_lands in walk(profile) if wound_lands), start=Fraction(0)
    )
    logger.debug("attack walk: p_unsaved = %s = %.4f", unsaved, float(unsaved))
    return AttackResolution(p_unsaved=unsaved)


def walk(profile: AttackProfile) -> Iterator[tuple[Fraction, bool]]:
    """Enumerate every dice path of one attack.

    Yields:
        ``(probability, unsaved_wound)`` per path; the probabilities of
        all paths sum to exactly 1.
    """
    for p_hit, hit in _roll_to_hit(profile.hit_target):
        if not hit:
            yield p_hit, False
            continue
        for p_wound, wounded in _roll(profile.wound_target, clamp=False):
            if not wounded:
                yield p_hit * p_wound, False
                continue
            for p_save, saved in _roll(profile.save_target, clamp=True):
                if saved:
                    yield p_hit * p_wound * p_save, False
                    continue
                for p_ward, warded in _roll(profile.ward_target, clamp=True):
                    yield p_hit * p_wound * p_save * p_ward, not warded


def _roll_to_hit(target: int) -> Iterator[tuple[Fraction, bool]]:
    # Mirrors charts.hit_probability: a natural 1 always fails; targets of
    # 7+ resolve as a natural 6 confirmed at CONFIRM_TARGETS[target]; 10+
    # is impossible.
    if target <= 6:
        yield from _roll(target, clamp=True)
        return
    confirm = CONFIRM_TARGETS.get(target)
    for face in _FACES:
        if face != 6 or confirm is None:
            yield _FACE, False
        else:
            for confirm_face in _FACES:
                yield _FACE * _FACE, confirm_face >= confirm


def _roll(target: int | None, *, clamp: bool) -> Iterator[tuple[Fraction, bool]]:
    # A None target is a roll that cannot succeed (no save; a "-" on the
    # wound chart): one certain branch, no die consumed. ``clamp`` mirrors
    # the charts' "a natural 1 always fails" handling; wound targets come
    # pre-clamped by the chart, so their roll is unclamped.
    if target is None:
        yield Fraction(1), False
        return
    threshold = max(target, 2) if clamp else target
    for face in _FACES:
        yield _FACE, face >= threshold
