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
from typing import ClassVar

from avelorn.tow.schema.rule import NaturalRoll
from avelorn.tow.schema.stage import Stage

logger = logging.getLogger(__name__)

_FACE = Fraction(1, 6)
_FACES = range(1, 7)


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


@dataclass(frozen=True)
class Roll:
    """The dice of one printed step: every step knows what it rolls.

    The common shape of everything a phase's steps roll — an attack
    die, a 2D6 Leadership test, whatever the step prints. Subclasses
    own their printed semantics and answer :meth:`chance`; a phase's
    ``steps`` tuple is made of these, one kind per step.
    """

    stage: ClassVar[Stage]

    def chance(self) -> Fraction:
        """The probability this roll succeeds; each kind answers its own.

        Returns:
            The exact success probability.

        Raises:
            NotImplementedError: the base knows no dice of its own.
        """
        raise NotImplementedError


@dataclass(frozen=True)
class AttackRoll(Roll):
    """One roll of the printed attack sequence: its stage, its target, its die.

    Subclasses own their printed semantics — everything the die means
    beyond its face. :meth:`branches` enumerates the roll exactly,
    ``(probability, natural face, success)`` per branch, probabilities
    summing to 1. A :class:`RollState` target takes no die (face 0), so
    face-triggered rules cannot fire there; every rolled die clamps at
    2+ — a natural 1 always fails, regardless of modifiers (the rulebook
    states it per roll, e.g. "Rolls of a Natural 1", p.140).
    """

    target: RollTarget

    def branches(self) -> Iterator[tuple[Fraction, int, bool]]:
        """Enumerate this roll's die, branch by branch.

        Yields:
            ``(probability, natural face, success)`` per branch.
        """
        if self.target is RollState.IMPOSSIBLE:
            yield Fraction(1), 0, False
            return
        if self.target is RollState.AUTOMATIC:
            yield Fraction(1), 0, True
            return
        threshold = max(self.target, 2)
        for face in _FACES:
            yield _FACE, face, face >= threshold

    def chance(self) -> Fraction:
        """The probability this roll succeeds, summed over its branches.

        The reported per-stage figures (charts) derive from this, so
        the die's semantics have one declaration.

        Returns:
            The exact success probability.
        """
        return sum((p for p, _, success in self.branches() if success), Fraction(0))


# A To Hit target of 7+ resolves as a natural 6 confirmed at this
# target ("7 to Hit"); 10+ is impossible.
CONFIRM_TARGETS = {7: 4, 8: 5, 9: 6}


@dataclass(frozen=True)
class RollToHitShooting(AttackRoll):
    """The Roll to Hit of shooting: a target of 7+ confirms on a second die.

    Its combat peer is :class:`RollToHitCombat`; the rulebook prints
    them as separate sections (roll-to-hit-shooting).

    The yielded natural face is the first die's — for the confirmation,
    the 6 that is being confirmed.
    """

    stage: ClassVar[Stage] = Stage.ROLL_TO_HIT

    def branches(self) -> Iterator[tuple[Fraction, int, bool]]:
        """Enumerate the shooting To Hit die, confirming 7+ targets.

        Yields:
            ``(probability, natural face, success)`` per branch.
        """
        if isinstance(self.target, RollState) or self.target <= 6:
            yield from super().branches()
            return
        confirm = CONFIRM_TARGETS.get(self.target)
        for face in _FACES:
            if face != 6 or confirm is None:
                yield _FACE, face, False
            else:
                for confirm_face in _FACES:
                    yield _FACE * _FACE, face, confirm_face >= confirm


@dataclass(frozen=True)
class RollToHitCombat(AttackRoll):
    """The Roll to Hit of close combat: a natural 6 always hits, a natural 1 always misses.

    Its shooting peer is :class:`RollToHitShooting`; here no
    confirmation step exists (roll-to-hit-combat) — a target above 6
    still hits one time in six.
    """

    stage: ClassVar[Stage] = Stage.ROLL_TO_HIT

    def branches(self) -> Iterator[tuple[Fraction, int, bool]]:
        """Enumerate the close-combat To Hit die.

        Yields:
            ``(probability, natural face, success)`` per branch.
        """
        if isinstance(self.target, RollState):
            yield from super().branches()
            return
        threshold = max(self.target, 2)
        for face in _FACES:
            yield _FACE, face, face == 6 or face >= threshold


@dataclass(frozen=True)
class RollToWound(AttackRoll):
    """The Roll to Wound: the shared die, no specials of its own yet.

    Wound-roll particulars join here when a rule needs them — nothing
    modelled today pushes a wound target beyond the printed chart.
    """

    stage: ClassVar[Stage] = Stage.ROLL_TO_WOUND


@dataclass(frozen=True)
class Save(AttackRoll):
    """A save: a target worsened past 6+ cannot be attempted.

    No roll is taken — no die, no natural face — the walk-side mirror of
    the chart, which yields no save for a target past 6+. To Hit
    differs: its 7+ still rolls, and confirms.
    """

    def branches(self) -> Iterator[tuple[Fraction, int, bool]]:
        """Enumerate the save's die; past 6+ there is nothing to roll.

        Yields:
            ``(probability, natural face, success)`` per branch.
        """
        if isinstance(self.target, int) and self.target > 6:
            yield Fraction(1), 0, False
            return
        yield from super().branches()


@dataclass(frozen=True)
class ArmourSave(Save):
    """The armour save, as Make Armour Saves rolls it."""

    stage: ClassVar[Stage] = Stage.MAKE_ARMOUR_SAVES


@dataclass(frozen=True)
class WardSave(Save):
    """The ward save; save semantics, its own stage."""

    stage: ClassVar[Stage] = Stage.WARD_SAVES


@dataclass(frozen=True)
class AttackProfile:
    """One attack: its rolls in printed sequence, and outcome semantics.

    Built by :meth:`shooting` or :meth:`melee` — the two printed attack
    sequences differ only in how their Roll to Hit resolves, and each
    roll owns its own semantics. :meth:`target` and :meth:`with_target`
    address targets by the stage whose roll they decide.
    ``unsaved_outcome`` is the class an unsaved wound resolves to;
    transforms escalate it (a Killing Blow turns it into an instant
    kill for the rest of the walk).
    """

    rolls: tuple[AttackRoll, ...]
    unsaved_outcome: Outcome = Outcome.UNSAVED_WOUND

    @classmethod
    def shooting(
        cls,
        *,
        hit_target: RollTarget,
        wound_target: RollTarget,
        save_target: RollTarget,
        ward_target: RollTarget,
        unsaved_outcome: Outcome = Outcome.UNSAVED_WOUND,
    ) -> "AttackProfile":
        """A shooting attack: its Roll to Hit confirms targets of 7+.

        Returns:
            The profile, each target on its sequence's own roll.
        """
        return cls(
            rolls=(
                RollToHitShooting(hit_target),
                RollToWound(wound_target),
                ArmourSave(save_target),
                WardSave(ward_target),
            ),
            unsaved_outcome=unsaved_outcome,
        )

    @classmethod
    def melee(
        cls,
        *,
        hit_target: RollTarget,
        wound_target: RollTarget,
        save_target: RollTarget,
        ward_target: RollTarget,
        unsaved_outcome: Outcome = Outcome.UNSAVED_WOUND,
    ) -> "AttackProfile":
        """A close-combat attack: a natural 6 always hits, a natural 1 always misses.

        Returns:
            The profile, each target on its sequence's own roll.
        """
        return cls(
            rolls=(
                RollToHitCombat(hit_target),
                RollToWound(wound_target),
                ArmourSave(save_target),
                WardSave(ward_target),
            ),
            unsaved_outcome=unsaved_outcome,
        )

    def roll(self, stage: Stage) -> AttackRoll:
        """The roll of ``stage``, semantics and current target together.

        Returns:
            The roll that stage makes.

        Raises:
            KeyError: ``stage`` rolls nothing in this attack.
        """
        for roll in self.rolls:
            if roll.stage is stage:
                return roll
        raise KeyError(stage)

    def target(self, stage: Stage) -> RollTarget:
        """The target of ``stage``'s roll; a rollless stage is :meth:`roll`'s KeyError.

        Returns:
            The roll target that stage reads.
        """
        return self.roll(stage).target

    def with_target(self, stage: Stage, target: RollTarget) -> "AttackProfile":
        """A copy with the target of ``stage``'s roll replaced (KeyError via :meth:`roll`).

        Returns:
            The updated profile.
        """
        self.roll(stage)  # the stage must roll something here
        return replace(
            self,
            rolls=tuple(
                replace(roll, target=target) if roll.stage is stage else roll
                for roll in self.rolls
            ),
        )

    @property
    def hit_target(self) -> RollTarget:
        """The Roll to Hit's target."""
        return self.target(Stage.ROLL_TO_HIT)

    @property
    def wound_target(self) -> RollTarget:
        """The Roll to Wound's target."""
        return self.target(Stage.ROLL_TO_WOUND)

    @property
    def save_target(self) -> RollTarget:
        """The armour save's target."""
        return self.target(Stage.MAKE_ARMOUR_SAVES)

    @property
    def ward_target(self) -> RollTarget:
        """The ward save's target."""
        return self.target(Stage.WARD_SAVES)


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
) -> AttackResolution:
    """Resolve one attack by walking its dice exactly.

    ``modifiers`` are the compiled records of printed conditional
    modifiers; ``transforms`` the bespoke code hooks. How each die
    resolves is the profile's own rolls' knowledge — a shooting attack
    confirms 7+ To Hit, a close-combat one never does — fixed where the
    profile was built (:meth:`AttackProfile.shooting` / ``melee``).

    Returns:
        The exact per-attack outcome-class probabilities.
    """
    outcomes: dict[Outcome, Fraction] = {}
    for p_path, outcome in walk(profile, modifiers, transforms):
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

    hit_profile = before_roll(Stage.ROLL_TO_HIT, profile)
    for p_hit, hit_face, hit in hit_profile.roll(Stage.ROLL_TO_HIT).branches():
        if not hit:
            yield p_hit, Outcome.NONE
            continue
        wound_profile = before_roll(
            Stage.ROLL_TO_WOUND, on_success(Stage.ROLL_TO_HIT, hit_face, hit_profile)
        )
        for p_wound, wound_face, wounded in wound_profile.roll(Stage.ROLL_TO_WOUND).branches():
            if not wounded:
                yield p_hit * p_wound, Outcome.NONE
                continue
            save_profile = before_roll(
                Stage.MAKE_ARMOUR_SAVES, on_success(Stage.ROLL_TO_WOUND, wound_face, wound_profile)
            )
            for p_save, _, saved in save_profile.roll(Stage.MAKE_ARMOUR_SAVES).branches():
                if saved:
                    yield p_hit * p_wound * p_save, Outcome.NONE
                    continue
                ward_profile = before_roll(Stage.WARD_SAVES, save_profile)
                for p_ward, _, warded in ward_profile.roll(Stage.WARD_SAVES).branches():
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
