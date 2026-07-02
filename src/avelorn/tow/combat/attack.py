"""Exact resolution of a single attack as a walk over its dice.

Stage names come verbatim from the printed shooting-phase sequence
(tow.whfb.app/the-shooting-phase): Roll to Hit, Roll to Wound, Make
Armour Saves, Ward Saves. The walk enumerates every die face branch by
branch — including the 7+ to Hit confirmation roll — so rules can hook
individual stages and dice ("on a natural 6 To Wound" needs the die,
not just its probability). Probabilities are exact fractions, converted
to float at the caller's edge.

Rules hook the walk as :class:`Transform`s: target modifications apply
before a stage's roll, on-success effects see the natural face and
shape the rest of the walk. No rules ship yet; the hooks are exercised
by test doubles.
"""

import logging
from collections.abc import Callable, Iterator, Sequence
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
class Transform:
    """A rule's hook into one stage of the attack sequence.

    ``modify_targets`` runs before the stage's roll and returns updated
    targets ("+1 to hit"). ``on_success`` runs after the stage's roll
    succeeds, sees the natural face, and returns the targets used for
    the rest of the walk ("on a natural 6 To Wound, Armour Piercing
    improves"). For the 7+ to Hit confirmation, the natural face is the
    6 that is being confirmed. Transforms on one stage apply in
    ascending ``priority`` order.

    ``on_success`` only has effect on stages whose success continues the
    attack (Roll to Hit, Roll to Wound); a passed save ends it.
    """

    stage: Stage
    priority: int = 0
    modify_targets: Callable[[AttackProfile], AttackProfile] | None = None
    on_success: Callable[[int, AttackProfile], AttackProfile] | None = None


@dataclass(frozen=True)
class AttackResolution:
    """Exact outcome probabilities of a single attack."""

    p_unsaved: Fraction


def resolve_attack(
    profile: AttackProfile, transforms: Sequence[Transform] = ()
) -> AttackResolution:
    """Resolve one attack by walking its dice exactly.

    Returns:
        The exact per-attack outcome probabilities; today just the
        unsaved wound.
    """
    unsaved = sum(
        (p_path for p_path, wound_lands in walk(profile, transforms) if wound_lands),
        start=Fraction(0),
    )
    logger.debug("attack walk: p_unsaved = %s = %.4f", unsaved, float(unsaved))
    return AttackResolution(p_unsaved=unsaved)


def walk(
    profile: AttackProfile, transforms: Sequence[Transform] = ()
) -> Iterator[tuple[Fraction, bool]]:
    """Enumerate every dice path of one attack, applying transforms.

    Yields:
        ``(probability, unsaved_wound)`` per path; the probabilities of
        all paths sum to exactly 1.
    """
    hooked = _by_stage(transforms)
    hit_profile = _modify(hooked[Stage.ROLL_TO_HIT], profile)
    for p_hit, hit_face, hit in _roll_to_hit(hit_profile.hit_target):
        if not hit:
            yield p_hit, False
            continue
        wound_profile = _modify(
            hooked[Stage.ROLL_TO_WOUND],
            _on_success(hooked[Stage.ROLL_TO_HIT], hit_face, hit_profile),
        )
        for p_wound, wound_face, wounded in _roll(wound_profile.wound_target, clamp=False):
            if not wounded:
                yield p_hit * p_wound, False
                continue
            save_profile = _modify(
                hooked[Stage.MAKE_ARMOUR_SAVES],
                _on_success(hooked[Stage.ROLL_TO_WOUND], wound_face, wound_profile),
            )
            for p_save, _, saved in _roll(save_profile.save_target, clamp=True):
                if saved:
                    yield p_hit * p_wound * p_save, False
                    continue
                ward_profile = _modify(hooked[Stage.WARD_SAVES], save_profile)
                for p_ward, _, warded in _roll(ward_profile.ward_target, clamp=True):
                    yield p_hit * p_wound * p_save * p_ward, not warded


def _by_stage(transforms: Sequence[Transform]) -> dict[Stage, list[Transform]]:
    hooked: dict[Stage, list[Transform]] = {stage: [] for stage in Stage}
    for transform in sorted(transforms, key=lambda t: t.priority):
        hooked[transform.stage].append(transform)
    return hooked


def _modify(transforms: list[Transform], profile: AttackProfile) -> AttackProfile:
    for transform in transforms:
        if transform.modify_targets is not None:
            profile = transform.modify_targets(profile)
    return profile


def _on_success(transforms: list[Transform], face: int, profile: AttackProfile) -> AttackProfile:
    for transform in transforms:
        if transform.on_success is not None:
            profile = transform.on_success(face, profile)
    return profile


def _roll_to_hit(target: int) -> Iterator[tuple[Fraction, int, bool]]:
    # Mirrors charts.hit_probability: a natural 1 always fails; targets of
    # 7+ resolve as a natural 6 confirmed at CONFIRM_TARGETS[target]; 10+
    # is impossible. The yielded face is the natural die.
    if target <= 6:
        yield from _roll(target, clamp=True)
        return
    confirm = CONFIRM_TARGETS.get(target)
    for face in _FACES:
        if face != 6 or confirm is None:
            yield _FACE, face, False
        else:
            for confirm_face in _FACES:
                yield _FACE * _FACE, face, confirm_face >= confirm


def _roll(target: int | None, *, clamp: bool) -> Iterator[tuple[Fraction, int, bool]]:
    # A None target is a roll that cannot succeed (no save; a "-" on the
    # wound chart): one certain branch, no die consumed (the face is never
    # read on a failed branch). ``clamp`` mirrors the charts' "a natural 1
    # always fails" handling; wound targets come pre-clamped by the chart,
    # so their roll is unclamped.
    if target is None:
        yield Fraction(1), 0, False
        return
    threshold = max(target, 2) if clamp else target
    for face in _FACES:
        yield _FACE, face, face >= threshold
