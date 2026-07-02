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
shape the rest of the walk. An attack ends in an :class:`Outcome`
class — nothing, an unsaved wound, or the rulebook's "Instant Kills"
shape ("loses all of its remaining Wounds") — which transforms may
escalate. No rules ship yet; the hooks are exercised by test doubles.
"""

import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
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


class Outcome(StrEnum):
    """What one attack ends as.

    ``INSTANT_KILL`` is named after the rulebook's "Instant Kills"
    section: the model is removed regardless of its remaining Wounds.
    """

    NONE = "none"
    UNSAVED_WOUND = "unsaved-wound"
    INSTANT_KILL = "instant-kill"


class RollState(StrEnum):
    """A roll that is not decided by a die.

    ``IMPOSSIBLE`` cannot succeed and takes no roll: the wound chart's
    printed "-" ("Too Tough to Wound"), or a model with no save.
    ``AUTOMATIC`` succeeds without a roll: the printed "Automatic Hits"
    and attacks that "wound automatically". No die means no natural
    face, so face-triggered rules cannot fire — which is exactly the
    printed Killing Blow note ("if an attack wounds automatically, this
    special rule cannot be used"), emerging from the model.
    """

    IMPOSSIBLE = "impossible"
    AUTOMATIC = "automatic"


type RollTarget = int | RollState


@dataclass(frozen=True)
class AttackProfile:
    """Roll targets and outcome semantics for one attack.

    Each target is either the required roll or a :class:`RollState`.
    ``unsaved_outcome`` is the class an unsaved wound resolves to;
    transforms escalate it (a Killing Blow turns it into an instant
    kill for the rest of the walk).
    """

    hit_target: RollTarget
    wound_target: RollTarget
    save_target: RollTarget
    ward_target: RollTarget
    unsaved_outcome: Outcome = Outcome.UNSAVED_WOUND


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
    """Exact outcome-class probabilities of a single attack."""

    outcomes: Mapping[Outcome, Fraction] = field(default_factory=dict)

    @property
    def p_unsaved(self) -> Fraction:
        """Probability of an unsaved wound of any class.

        A Killing Blow is still an unsaved wound ("suffers an unsaved
        wound from a Killing Blow"), so this sums both classes.

        Returns:
            The unsaved-wound plus instant-kill mass.
        """
        return self.p_of(Outcome.UNSAVED_WOUND) + self.p_of(Outcome.INSTANT_KILL)

    def p_of(self, outcome: Outcome) -> Fraction:
        """Probability of one outcome class.

        Returns:
            The class's mass, or 0 if the walk never reached it.
        """
        return self.outcomes.get(outcome, Fraction(0))


def resolve_attack(
    profile: AttackProfile, transforms: Sequence[Transform] = ()
) -> AttackResolution:
    """Resolve one attack by walking its dice exactly.

    Returns:
        The exact per-attack outcome-class probabilities.
    """
    outcomes: dict[Outcome, Fraction] = {}
    for p_path, outcome in walk(profile, transforms):
        outcomes[outcome] = outcomes.get(outcome, Fraction(0)) + p_path
    resolution = AttackResolution(outcomes=outcomes)
    logger.debug(
        "attack walk: p_unsaved = %s = %.4f (instant kill %s)",
        resolution.p_unsaved,
        float(resolution.p_unsaved),
        resolution.p_of(Outcome.INSTANT_KILL),
    )
    return resolution


def walk(
    profile: AttackProfile, transforms: Sequence[Transform] = ()
) -> Iterator[tuple[Fraction, Outcome]]:
    """Enumerate every dice path of one attack, applying transforms.

    Yields:
        ``(probability, outcome)`` per path; the probabilities of all
        paths sum to exactly 1.
    """
    hooked = _by_stage(transforms)
    hit_profile = _modify(hooked[Stage.ROLL_TO_HIT], profile)
    for p_hit, hit_face, hit in _roll_to_hit(hit_profile.hit_target):
        if not hit:
            yield p_hit, Outcome.NONE
            continue
        wound_profile = _modify(
            hooked[Stage.ROLL_TO_WOUND],
            _on_success(hooked[Stage.ROLL_TO_HIT], hit_face, hit_profile),
        )
        for p_wound, wound_face, wounded in _roll(wound_profile.wound_target, clamp=False):
            if not wounded:
                yield p_hit * p_wound, Outcome.NONE
                continue
            save_profile = _modify(
                hooked[Stage.MAKE_ARMOUR_SAVES],
                _on_success(hooked[Stage.ROLL_TO_WOUND], wound_face, wound_profile),
            )
            for p_save, _, saved in _roll(save_profile.save_target, clamp=True):
                if saved:
                    yield p_hit * p_wound * p_save, Outcome.NONE
                    continue
                ward_profile = _modify(hooked[Stage.WARD_SAVES], save_profile)
                for p_ward, _, warded in _roll(ward_profile.ward_target, clamp=True):
                    yield (
                        p_hit * p_wound * p_save * p_ward,
                        Outcome.NONE if warded else ward_profile.unsaved_outcome,
                    )


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


def _roll_to_hit(target: RollTarget) -> Iterator[tuple[Fraction, int, bool]]:
    # Mirrors charts.hit_probability: a natural 1 always fails; targets of
    # 7+ resolve as a natural 6 confirmed at CONFIRM_TARGETS[target]; 10+
    # is impossible. The yielded face is the natural die.
    if isinstance(target, RollState) or target <= 6:
        yield from _roll(target, clamp=True)
        return
    confirm = CONFIRM_TARGETS.get(target)
    for face in _FACES:
        if face != 6 or confirm is None:
            yield _FACE, face, False
        else:
            for confirm_face in _FACES:
                yield _FACE * _FACE, face, confirm_face >= confirm


def _roll(target: RollTarget, *, clamp: bool) -> Iterator[tuple[Fraction, int, bool]]:
    # A RollState is decided without a die: one certain branch, face 0
    # (never a natural anything, so face-triggered transforms cannot
    # fire). ``clamp`` mirrors the charts' "a natural 1 always fails"
    # handling; wound targets come pre-clamped by the chart, so their
    # roll is unclamped.
    if target is RollState.IMPOSSIBLE:
        yield Fraction(1), 0, False
        return
    if target is RollState.AUTOMATIC:
        yield Fraction(1), 0, True
        return
    threshold = max(target, 2) if clamp else target
    for face in _FACES:
        yield _FACE, face, face >= threshold
