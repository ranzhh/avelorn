"""Exact resolution of a single attack as a walk over its dice.

Stage names come verbatim from the printed shooting-phase sequence
(tow.whfb.app/the-shooting-phase): Roll to Hit, Roll to Wound, Make
Armour Saves, Ward Saves. The walk enumerates every die face branch by
branch — including the 7+ to Hit confirmation roll — so rules can hook
individual stages and dice ("on a natural 6 To Wound" needs the die,
not just its probability). Probabilities are exact fractions, converted
to float at the caller's edge.

Printed conditional modifiers reach the walk as :class:`Modifier`
records — which roll's target moves, by how much, on which natural
face — readable as data. Bespoke rules the records cannot say hook in
as :class:`Transform` code. An attack ends in an :class:`Outcome`
class — nothing, an unsaved wound, or the rulebook's "Instant Kills"
shape ("loses all of its remaining Wounds") — which transforms may
escalate.
"""

import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from fractions import Fraction

from avelorn.tow.combat.charts import CONFIRM_TARGETS
from avelorn.tow.schema.rule import NaturalRoll
from avelorn.tow.schema.stage import Stage

logger = logging.getLogger(__name__)

_FACE = Fraction(1, 6)
_FACES = range(1, 7)


class HitRoll(StrEnum):
    """How a To Hit roll resolves beyond the die's face.

    Shooting confirms a target of 7+ with a second roll ("7 to Hit");
    close combat has no confirmation step — a natural 6 always hits and a
    natural 1 always misses, regardless of modifiers
    (the-combat-phase/roll-to-hit-combat). The two stages share the rest
    of the walk.
    """

    SHOOTING = "shooting"
    MELEE = "melee"


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


def roll_target(target: int | None) -> RollTarget:
    """Lift a chart target into a roll target.

    The charts speak the printed convention: None means the roll is not
    taken and cannot succeed ("-" on the wound chart; no save).

    Returns:
        The numeric target unchanged, or ``RollState.IMPOSSIBLE`` for None.
    """
    return RollState.IMPOSSIBLE if target is None else target


# Which of the profile's targets each stage's roll reads — declared
# beside the profile so the stage-to-target correspondence has one home.
_TARGETS = {
    Stage.ROLL_TO_HIT: "hit_target",
    Stage.ROLL_TO_WOUND: "wound_target",
    Stage.MAKE_ARMOUR_SAVES: "save_target",
    Stage.WARD_SAVES: "ward_target",
}


@dataclass(frozen=True)
class AttackProfile:
    """Roll targets and outcome semantics for one attack.

    Each target is either the required roll or a :class:`RollState`;
    :meth:`target` and :meth:`with_target` address them by the stage
    whose roll they decide, so callers need not know the field names.
    ``unsaved_outcome`` is the class an unsaved wound resolves to;
    transforms escalate it (a Killing Blow turns it into an instant
    kill for the rest of the walk).
    """

    hit_target: RollTarget
    wound_target: RollTarget
    save_target: RollTarget
    ward_target: RollTarget
    unsaved_outcome: Outcome = Outcome.UNSAVED_WOUND

    def target(self, stage: Stage) -> RollTarget:
        """The target of ``stage``'s roll; a stage that rolls nothing is a KeyError.

        Returns:
            The roll target that stage reads.
        """
        return getattr(self, _TARGETS[stage])

    def with_target(self, stage: Stage, target: RollTarget) -> "AttackProfile":
        """A copy with ``stage``'s roll target replaced; a rollless stage is a KeyError.

        Returns:
            The updated profile.
        """
        return replace(self, **{_TARGETS[stage]: target})


@dataclass(frozen=True)
class Modifier:
    """One compiled modifier: move a roll's target by a signed amount.

    The declarative form of the printed conditional modifiers — what the
    rules compiler emits and the walk interprets, readable as data:
    ``lands_on`` is the roll whose target moves, ``move`` the movement
    with the printed sign conventions already folded in, and ``trigger``
    the natural roll that fires it (the change then holds for the rest
    of that attack) — or None for a modifier applied before its roll on
    every attack. A trigger always precedes its landing roll; the
    compiler refuses the rest.

    What a moved target *means* stays each roll's own knowledge (a To
    Hit of 7+ confirms, a save past 6+ takes no roll), and a target
    that is no die (a RollState) has nothing to move.
    """

    lands_on: Stage
    move: int
    trigger: NaturalRoll | None = None


@dataclass(frozen=True)
class Transform:
    """A bespoke rule's code hook into one stage of the attack sequence.

    The escape hatch for what a :class:`Modifier` record cannot say —
    escalating the outcome class (Killing Blow), rewriting targets from
    arbitrary state. Printed conditional modifiers compile to records
    instead; a Transform is hand-written, as itself.

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
    """Exact outcome-class probabilities of a single attack.

    ``hit_target`` is the effective Roll to Hit target after transforms'
    pre-roll modifications — the figure to report alongside the
    probabilities. (Later stages' targets can depend on earlier dice, so
    only the first stage's effective target is well defined up front.)
    """

    outcomes: Mapping[Outcome, Fraction] = field(default_factory=dict)
    hit_target: RollTarget = 0

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
    profile: AttackProfile,
    modifiers: Sequence[Modifier] = (),
    transforms: Sequence[Transform] = (),
    *,
    hit_roll: HitRoll,
) -> AttackResolution:
    """Resolve one attack by walking its dice exactly.

    ``modifiers`` are the compiled records of printed conditional
    modifiers; ``transforms`` the bespoke code hooks. ``hit_roll``
    selects how the To Hit die resolves (shooting's 7+ confirmation
    versus close combat's natural-6-always-hits); it leaves every other
    stage unchanged. It is required — the phase is known at the calling
    helper (``shoot``/``strike``), never assumed here.

    Returns:
        The exact per-attack outcome-class probabilities.
    """
    outcomes: dict[Outcome, Fraction] = {}
    for p_path, outcome in walk(profile, modifiers, transforms, hit_roll=hit_roll):
        outcomes[outcome] = outcomes.get(outcome, Fraction(0)) + p_path
    before, _ = _plan(modifiers)
    effective = _before_roll(Stage.ROLL_TO_HIT, profile, before, _by_stage(transforms))
    resolution = AttackResolution(outcomes=outcomes, hit_target=effective.hit_target)
    logger.debug(
        "attack walk: p_unsaved = %s = %.4f (instant kill %s)",
        resolution.p_unsaved,
        float(resolution.p_unsaved),
        resolution.p_of(Outcome.INSTANT_KILL),
    )
    return resolution


def walk(
    profile: AttackProfile,
    modifiers: Sequence[Modifier] = (),
    transforms: Sequence[Transform] = (),
    *,
    hit_roll: HitRoll,
) -> Iterator[tuple[Fraction, Outcome]]:
    """Enumerate every dice path of one attack, applying the rules' changes.

    At every stage: untriggered modifiers landing there move its target,
    bespoke hooks run, the die rolls, and a success fires the modifiers
    triggered by its natural face — shaping the rolls still to come.

    Yields:
        ``(probability, outcome)`` per path; the probabilities of all
        paths sum to exactly 1.
    """
    before, fired = _plan(modifiers)
    hooked = _by_stage(transforms)

    def before_roll(stage: Stage, prof: AttackProfile) -> AttackProfile:
        return _before_roll(stage, prof, before, hooked)

    def on_success(stage: Stage, face: int, prof: AttackProfile) -> AttackProfile:
        shown = [m for m in fired[stage] if m.trigger is not None and m.trigger.face == face]
        return _on_success(hooked[stage], face, _moved(prof, shown))

    roll_hit = _roll_melee_hit if hit_roll is HitRoll.MELEE else _roll_to_hit
    hit_profile = before_roll(Stage.ROLL_TO_HIT, profile)
    for p_hit, hit_face, hit in roll_hit(hit_profile.hit_target):
        if not hit:
            yield p_hit, Outcome.NONE
            continue
        wound_profile = before_roll(
            Stage.ROLL_TO_WOUND, on_success(Stage.ROLL_TO_HIT, hit_face, hit_profile)
        )
        for p_wound, wound_face, wounded in _roll(wound_profile.wound_target):
            if not wounded:
                yield p_hit * p_wound, Outcome.NONE
                continue
            save_profile = before_roll(
                Stage.MAKE_ARMOUR_SAVES, on_success(Stage.ROLL_TO_WOUND, wound_face, wound_profile)
            )
            for p_save, _, saved in _roll_save(save_profile.save_target):
                if saved:
                    yield p_hit * p_wound * p_save, Outcome.NONE
                    continue
                ward_profile = before_roll(Stage.WARD_SAVES, save_profile)
                for p_ward, _, warded in _roll_save(ward_profile.ward_target):
                    yield (
                        p_hit * p_wound * p_save * p_ward,
                        Outcome.NONE if warded else ward_profile.unsaved_outcome,
                    )


def _plan(
    modifiers: Sequence[Modifier],
) -> tuple[dict[Stage, list[Modifier]], dict[Stage, list[Modifier]]]:
    # Where each record acts: untriggered modifiers act before their
    # landing roll; triggered ones act when their trigger's die succeeds.
    before: dict[Stage, list[Modifier]] = {stage: [] for stage in Stage}
    fired: dict[Stage, list[Modifier]] = {stage: [] for stage in Stage}
    for modifier in modifiers:
        if modifier.trigger is None:
            before[modifier.lands_on].append(modifier)
        else:
            fired[modifier.trigger.roll].append(modifier)
    return before, fired


def _moved(profile: AttackProfile, modifiers: list[Modifier]) -> AttackProfile:
    # Move each record's landing target; a target that is no die (a
    # RollState) has nothing to move.
    for modifier in modifiers:
        target = profile.target(modifier.lands_on)
        if isinstance(target, int):
            profile = profile.with_target(modifier.lands_on, target + modifier.move)
    return profile


def _before_roll(
    stage: Stage,
    profile: AttackProfile,
    before: dict[Stage, list[Modifier]],
    hooked: dict[Stage, list[Transform]],
) -> AttackProfile:
    # Records first, then bespoke hooks: a hand-written Transform sees
    # the targets the printed modifiers already moved.
    return _modify(hooked[stage], _moved(profile, before[stage]))


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
        yield from _roll(target)
        return
    confirm = CONFIRM_TARGETS.get(target)
    for face in _FACES:
        if face != 6 or confirm is None:
            yield _FACE, face, False
        else:
            for confirm_face in _FACES:
                yield _FACE * _FACE, face, confirm_face >= confirm


def _roll_melee_hit(target: RollTarget) -> Iterator[tuple[Fraction, int, bool]]:
    # Close combat has no 7+ confirmation: a natural 6 always hits and a
    # natural 1 always misses, regardless of modifiers
    # (the-combat-phase/roll-to-hit-combat). This differs from _roll only
    # at targets of 7+, where a natural 6 still hits rather than failing.
    # RollStates carry no die, so no natural face fires — deferred to _roll.
    if isinstance(target, RollState):
        yield from _roll(target)
        return
    threshold = max(target, 2)
    for face in _FACES:
        yield _FACE, face, face == 6 or face >= threshold


def _roll_save(target: RollTarget) -> Iterator[tuple[Fraction, int, bool]]:
    # A save worsened past 6+ cannot be attempted at all: the roll is
    # not taken — no die, no natural face — the walk-side mirror of the
    # chart-side charts.armour_save_target, which yields no save for a
    # target past 6+. This is the save rolls' own knowledge; To Hit
    # differs (a 7+ still rolls, confirmed by a second die), and each
    # roll states its own overflow, not the modifier that caused it.
    if isinstance(target, int) and target > 6:
        yield Fraction(1), 0, False
        return
    yield from _roll(target)


def _roll(target: RollTarget) -> Iterator[tuple[Fraction, int, bool]]:
    # A RollState is decided without a die: one certain branch, face 0
    # (never a natural anything, so face-triggered transforms cannot
    # fire). Every rolled die clamps at 2+: a natural 1 always fails,
    # "regardless of modifiers" — the rulebook states it per roll (e.g.
    # "Rolls of a Natural 1", p.140, for rolls To Wound), and transforms
    # may push any target below 2.
    if target is RollState.IMPOSSIBLE:
        yield Fraction(1), 0, False
        return
    if target is RollState.AUTOMATIC:
        yield Fraction(1), 0, True
        return
    threshold = max(target, 2)
    for face in _FACES:
        yield _FACE, face, face >= threshold
