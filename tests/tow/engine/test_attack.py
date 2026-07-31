"""Attack dice-walk tests.

Exact equivalence with the chart chain, plus transform hooks proven by
test doubles (no shipped rules).
"""

from dataclasses import replace
from fractions import Fraction

import pytest

from avelorn.tow.engine.attack import (
    AttackProfile,
    Modifier,
    Outcome,
    Reroll,
    RollState,
    RollTarget,
    Transform,
    resolve_attack,
    walk,
)
from avelorn.tow.engine.charts import hit_probability, save_probability, wound_probability
from avelorn.tow.schema.rule import NaturalRoll
from avelorn.tow.schema.stage import Stage

# Every shape the charts can hand the resolver: impossible (0, 10+) and
# clamped (1) hit targets, the 7+ confirmation band, "-" wound rows and
# no-save/no-ward cases included.
_HIT_TARGETS = range(0, 12)
_WOUND_TARGETS = (RollState.IMPOSSIBLE, 2, 3, 4, 5, 6)
_SAVE_TARGETS = (RollState.IMPOSSIBLE, 1, 2, 5, 6, 7)
_WARD_TARGETS = (RollState.IMPOSSIBLE, 4)


def _chart(target: RollTarget) -> int | None:
    # The charts speak the printed convention: None for a roll not taken.
    return None if isinstance(target, RollState) else target


def _profiles() -> list[AttackProfile]:
    return [
        AttackProfile.shooting(hit_target=h, wound_target=w, save_target=s, ward_target=ward)
        for h in _HIT_TARGETS
        for w in _WOUND_TARGETS
        for s in _SAVE_TARGETS
        for ward in _WARD_TARGETS
    ]


@pytest.mark.parametrize(
    "profile",
    _profiles(),
    ids=lambda p: f"h{p.hit_target}-w{p.wound_target}-s{p.save_target}-x{p.ward_target}",
)
def test_walk_matches_scalar_chain(profile: AttackProfile) -> None:
    """The dice walk reproduces hit x wound x save-fail x ward-fail exactly."""
    expected = (
        hit_probability(_chart(profile.hit_target) or 0)
        * wound_probability(_chart(profile.wound_target))
        * (1.0 - save_probability(_chart(profile.save_target)))
        * (1.0 - save_probability(_chart(profile.ward_target)))
    )
    assert float(resolve_attack(profile).p_unsaved) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("hit_target", _HIT_TARGETS)
def test_walk_is_exhaustive(hit_target: int) -> None:
    """Every path is enumerated: the walk's probabilities sum to exactly 1."""
    profile = AttackProfile.shooting(
        hit_target=hit_target, wound_target=4, save_target=5, ward_target=6
    )
    assert sum(p for p, _ in walk(profile)) == Fraction(1)


def test_seven_plus_confirmation_golden() -> None:
    """7+ to hit: a natural 6 confirmed at 4+ -> 1/6 * 1/2 hits (exact)."""
    profile = AttackProfile.shooting(
        hit_target=7,
        wound_target=2,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )
    assert resolve_attack(profile).p_unsaved == Fraction(1, 12) * Fraction(5, 6)


# --- Melee hit resolution: natural 6 always hits, no 7+ confirmation. ---


@pytest.mark.parametrize("hit_target", range(2, 7))
def test_melee_hit_matches_shooting_at_six_or_less(hit_target: int) -> None:
    """For targets of 2..6 the two hit rolls agree: a 6 hits in both."""
    targets: dict = dict(
        hit_target=hit_target, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    shooting = resolve_attack(AttackProfile.shooting(**targets)).p_unsaved
    melee = resolve_attack(AttackProfile.melee(**targets)).p_unsaved
    assert melee == shooting


def test_melee_hits_on_natural_six_past_the_chart() -> None:
    """A modified 7+ target still hits on a natural 6 (1/6), with no confirm.

    Shooting confirms a 7+ (natural 6 re-rolled), so its hit chance is
    lower; melee just takes the natural 6.
    """
    targets: dict = dict(
        hit_target=7,
        wound_target=RollState.AUTOMATIC,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )
    assert resolve_attack(AttackProfile.melee(**targets)).p_unsaved == Fraction(1, 6)
    # The shooting confirm makes 7+ strictly less likely than a flat 1/6.
    assert resolve_attack(AttackProfile.shooting(**targets)).p_unsaved < Fraction(1, 6)


def test_melee_hit_still_fails_on_a_natural_one() -> None:
    """Even at a 1+ target a natural 1 misses; melee hit chance caps at 5/6."""
    profile = AttackProfile.melee(
        hit_target=1,
        wound_target=RollState.AUTOMATIC,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )
    assert resolve_attack(profile).p_unsaved == Fraction(5, 6)


@pytest.mark.parametrize("hit_target", range(0, 12))
def test_melee_walk_is_exhaustive(hit_target: int) -> None:
    """The melee walk enumerates every path: probabilities sum to exactly 1."""
    profile = AttackProfile.melee(
        hit_target=hit_target, wound_target=4, save_target=5, ward_target=6
    )
    assert sum(p for p, _ in walk(profile)) == Fraction(1)


# --- Re-rolls: a failing die re-rolled once, natural-face restricted. ---


def _hit_only(hit_target: int) -> AttackProfile:
    # An attack that resolves on the To Hit roll alone: wound automatic, no save.
    return AttackProfile.melee(
        hit_target=hit_target,
        wound_target=RollState.AUTOMATIC,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )


def test_reroll_of_natural_ones_re_rolls_only_the_ones() -> None:
    """Re-rolling To Hit natural 1s spreads the 1's mass over a fresh roll.

    Hitting on 4+ is 1/2; the natural 1 (a miss) is re-rolled once and hits
    again on 4+, so the chance rises by 1/6 * 1/2 to 7/12 — the natural 2 and 3,
    misses that are not 1s, are left to stand (this is not "re-roll all misses").
    """
    profile = _hit_only(4)
    reroll = [Reroll(stage=Stage.ROLL_TO_HIT, on_natural=1)]
    assert resolve_attack(profile).p_unsaved == Fraction(1, 2)
    assert resolve_attack(profile, rerolls=reroll).p_unsaved == Fraction(7, 12)


def test_a_re_rolled_die_is_never_re_rolled_again() -> None:
    """A re-rolled natural 1 stands as a miss — no die is re-rolled twice.

    Hitting on 2+ is 5/6; re-rolling the natural 1 adds 1/6 * 5/6, and the
    fresh die's own natural 1 (1/36) stays a miss rather than re-rolling
    forever — the chance is 35/36, not 1.
    """
    assert resolve_attack(_hit_only(2), rerolls=[Reroll(Stage.ROLL_TO_HIT, 1)]).p_unsaved == (
        Fraction(35, 36)
    )


def test_unrestricted_reroll_re_rolls_every_miss() -> None:
    """A grant naming no face re-rolls every failing die at the stage.

    Hitting on 4+ is 1/2; re-rolling all three misses (1, 2, 3) once gives
    1/2 + 1/2 * 1/2 = 3/4.
    """
    assert resolve_attack(_hit_only(4), rerolls=[Reroll(Stage.ROLL_TO_HIT)]).p_unsaved == (
        Fraction(3, 4)
    )


def test_reroll_leaves_a_successful_die_alone() -> None:
    """Only failing dice are re-rolled; naming a hitting face changes nothing.

    On a 4+ target the natural 6 hits, so a (contrived) re-roll of natural 6s
    finds no failing die to re-roll — the chance is the unmodified 1/2.
    """
    assert resolve_attack(_hit_only(4), rerolls=[Reroll(Stage.ROLL_TO_HIT, 6)]).p_unsaved == (
        Fraction(1, 2)
    )


@pytest.mark.parametrize("hit_target", range(2, 7))
def test_reroll_walk_is_exhaustive(hit_target: int) -> None:
    """With a re-roll in play the walk still enumerates every path to mass 1."""
    profile = AttackProfile.melee(
        hit_target=hit_target, wound_target=4, save_target=5, ward_target=6
    )
    reroll = [Reroll(stage=Stage.ROLL_TO_HIT, on_natural=1)]
    assert sum(p for p, _ in walk(profile, rerolls=reroll)) == Fraction(1)


# --- Transform hooks, exercised by test doubles (no shipped rules). ---


def _worsen_save_on_natural_six(face: int, profile: AttackProfile) -> AttackProfile:
    # The Armour Bane (1) shape: a natural 6 To Wound improves AP by 1,
    # worsening the save target; past 6+ there is no save at all.
    if face != 6 or not isinstance(profile.save_target, int):
        return profile
    worsened = profile.save_target + 1
    return profile.with_target(
        Stage.MAKE_ARMOUR_SAVES, worsened if worsened <= 6 else RollState.IMPOSSIBLE
    )


def test_on_success_double_reproduces_armour_bane_golden() -> None:
    """On a natural 6 To Wound the save worsens; 13/54 is the spike golden.

    Hit 3+, wound 4+, save 5+: 2/3 * (2/6 * 2/3 + 1/6 * 5/6) = 13/54.
    """
    profile = AttackProfile.shooting(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    double = Transform(stage=Stage.ROLL_TO_WOUND, on_success=_worsen_save_on_natural_six)
    assert resolve_attack(profile, transforms=[double]).p_unsaved == Fraction(13, 54)


def test_modify_targets_double_equals_baked_in_modifier() -> None:
    """A +1-to-hit transform equals the same modifier baked into the target."""
    profile = AttackProfile.shooting(
        hit_target=4, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )

    def improve_hit(p: AttackProfile) -> AttackProfile:
        assert isinstance(p.hit_target, int)
        assert isinstance(p.hit_target, int)
        return p.with_target(Stage.ROLL_TO_HIT, p.hit_target - 1)

    plus_one = Transform(stage=Stage.ROLL_TO_HIT, modify_targets=improve_hit)
    baked = profile.with_target(Stage.ROLL_TO_HIT, 3)
    assert (
        resolve_attack(profile, transforms=[plus_one]).p_unsaved == resolve_attack(baked).p_unsaved
    )


def test_transforms_apply_in_priority_order() -> None:
    """Set-to and shift compose by ascending priority, not list position."""
    profile = AttackProfile.shooting(
        hit_target=2, wound_target=2, save_target=5, ward_target=RollState.IMPOSSIBLE
    )

    def set_to_two(priority: int) -> Transform:
        return Transform(
            stage=Stage.MAKE_ARMOUR_SAVES,
            priority=priority,
            modify_targets=lambda p: p.with_target(Stage.MAKE_ARMOUR_SAVES, 2),
        )

    def worsen_one(priority: int) -> Transform:
        def worsen(p: AttackProfile) -> AttackProfile:
            target = p.save_target if isinstance(p.save_target, int) else 6
            return p.with_target(Stage.MAKE_ARMOUR_SAVES, target + 1)

        return Transform(stage=Stage.MAKE_ARMOUR_SAVES, priority=priority, modify_targets=worsen)

    p_hit_wound = Fraction(5, 6) * Fraction(5, 6)
    # set(2) first, then +1 -> save on 3+ (fails 2/6).
    first = resolve_attack(profile, transforms=[worsen_one(1), set_to_two(0)]).p_unsaved
    assert first == p_hit_wound * Fraction(2, 6)
    # +1 first (5 -> 6), then set(2) -> save on 2+ (fails 1/6).
    second = resolve_attack(profile, transforms=[worsen_one(0), set_to_two(1)]).p_unsaved
    assert second == p_hit_wound * Fraction(1, 6)


def test_transforms_absent_leave_walk_unchanged() -> None:
    """An empty transform list is the identity."""
    profile = AttackProfile.shooting(hit_target=3, wound_target=4, save_target=5, ward_target=4)
    assert resolve_attack(profile, []).p_unsaved == resolve_attack(profile).p_unsaved
    assert sum(p for p, _ in walk(profile, [])) == Fraction(1)


def _killing_blow(face: int, profile: AttackProfile) -> AttackProfile:
    # The Killing Blow shape: a natural 6 To Wound skips the armour save
    # (Ward Saves attempted as normal) and the unsaved wound removes the
    # model outright.
    if face != 6:
        return profile
    return replace(
        profile.with_target(Stage.MAKE_ARMOUR_SAVES, RollState.IMPOSSIBLE),
        unsaved_outcome=Outcome.INSTANT_KILL,
    )


def test_instant_kill_double_reproduces_spike_classes() -> None:
    """Hit 3+, wound 4+, save 5+: classes are none 21/27, wound 4/27, kill 1/9."""
    profile = AttackProfile.shooting(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    double = Transform(stage=Stage.ROLL_TO_WOUND, on_success=_killing_blow)
    resolution = resolve_attack(profile, transforms=[double])
    assert resolution.p_of(Outcome.INSTANT_KILL) == Fraction(1, 9)
    assert resolution.p_of(Outcome.UNSAVED_WOUND) == Fraction(4, 27)
    assert resolution.p_unsaved == Fraction(1, 9) + Fraction(4, 27)
    assert sum(resolution.outcomes.values()) == Fraction(1)


def test_ward_save_applies_to_instant_kills() -> None:
    """A 5+ ward scales the kill class by its failure chance (4/6)."""
    profile = AttackProfile.shooting(hit_target=3, wound_target=4, save_target=5, ward_target=5)
    double = Transform(stage=Stage.ROLL_TO_WOUND, on_success=_killing_blow)
    resolution = resolve_attack(profile, transforms=[double])
    assert resolution.p_of(Outcome.INSTANT_KILL) == Fraction(1, 9) * Fraction(4, 6)


def test_outcomes_without_transforms_have_no_kill_class() -> None:
    """The vanilla walk never produces an instant kill."""
    profile = AttackProfile.shooting(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    resolution = resolve_attack(profile)
    assert resolution.p_of(Outcome.INSTANT_KILL) == 0
    assert resolution.p_unsaved == Fraction(2, 9)


def test_automatic_success_consumes_no_die() -> None:
    """An automatic wound succeeds without a roll: p_unsaved is p_hit."""
    profile = AttackProfile.shooting(
        hit_target=3,
        wound_target=RollState.AUTOMATIC,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )
    assert resolve_attack(profile).p_unsaved == Fraction(4, 6)
    assert sum(p for p, _ in walk(profile)) == Fraction(1)


def test_automatic_hit_skips_the_natural_one() -> None:
    """An automatic hit has no die, so not even a natural 1 fails it."""
    profile = AttackProfile.shooting(
        hit_target=RollState.AUTOMATIC,
        wound_target=4,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )
    assert resolve_attack(profile).p_unsaved == Fraction(3, 6)


def test_automatic_wounds_cannot_killing_blow() -> None:
    """No die means no natural 6, so face-triggered escalation never fires.

    The printed Killing Blow note — "if an attack wounds automatically,
    this special rule cannot be used" — emerges from the model.
    """
    profile = AttackProfile.shooting(
        hit_target=3,
        wound_target=RollState.AUTOMATIC,
        save_target=5,
        ward_target=RollState.IMPOSSIBLE,
    )
    double = Transform(stage=Stage.ROLL_TO_WOUND, on_success=_killing_blow)
    resolution = resolve_attack(profile, transforms=[double])
    assert resolution.p_of(Outcome.INSTANT_KILL) == 0
    assert resolution.p_of(Outcome.UNSAVED_WOUND) == Fraction(4, 6) * Fraction(4, 6)


def test_wound_modifier_cannot_defeat_the_natural_one() -> None:
    """A transform driving the wound target to 1 still fails on a natural 1.

    "Rolls of a Natural 1" (p.140): a roll To Wound of a natural 1 is
    always a fail, regardless of modifiers. A "+1 to wound" against a
    2+ target must yield 5/6, not 6/6.
    """
    profile = AttackProfile.shooting(
        hit_target=RollState.AUTOMATIC,
        wound_target=2,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )

    def improve_wound(p: AttackProfile) -> AttackProfile:
        assert isinstance(p.wound_target, int)
        return p.with_target(Stage.ROLL_TO_WOUND, p.wound_target - 1)

    plus_one = Transform(stage=Stage.ROLL_TO_WOUND, modify_targets=improve_wound)
    assert resolve_attack(profile, transforms=[plus_one]).p_unsaved == Fraction(5, 6)


def test_profile_targets_cover_exactly_the_per_attack_dice() -> None:
    """The profile carries a target for each per-attack die, and no other stage.

    Drift guard: the stage rows' ``dice`` (the rolls a natural-face event
    may name) and the profile's stage-addressed targets are one set — a
    roll joining either side must join both.
    """
    from avelorn.tow.schema.stage import Dice

    profile = AttackProfile.shooting(hit_target=3, wound_target=4, save_target=5, ward_target=6)
    for stage in Stage:
        if stage.dice is Dice.D6_PER_ATTACK:
            assert profile.with_target(stage, 2).target(stage) == 2
        else:
            with pytest.raises(KeyError):
                profile.target(stage)
            with pytest.raises(KeyError):
                profile.with_target(stage, 2)


# --- Modifier records: the walk interprets data, not closures ---


def test_untriggered_modifier_moves_its_roll_before_it_is_made() -> None:
    """A record with no trigger moves its landing roll's target every attack.

    Hit 4+ moved by -1 (a "+1 to hit"): 3+ at p = 4/6, and the effective
    target is reported.
    """
    profile = AttackProfile.shooting(
        hit_target=4,
        wound_target=RollState.AUTOMATIC,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )
    plus_one = Modifier(lands_on=Stage.ROLL_TO_HIT, move=-1)
    resolution = resolve_attack(profile, [plus_one])
    assert resolution.p_unsaved == Fraction(4, 6)
    assert resolution.hit_target == 3


def test_triggered_modifier_reproduces_the_armour_bane_golden() -> None:
    """The record form of Armour Bane: natural 6 To Wound, save +1.

    Hit 3+, wound 4+, save 5+ -> 13/54, the golden the closure doubles
    proved and the compiler now emits as data.
    """
    profile = AttackProfile.shooting(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    bane = Modifier(
        lands_on=Stage.MAKE_ARMOUR_SAVES,
        move=1,
        trigger=NaturalRoll(face=6, roll=Stage.ROLL_TO_WOUND),
    )
    assert resolve_attack(profile, [bane]).p_unsaved == Fraction(13, 54)


def test_triggered_modifier_stays_quiet_on_other_faces() -> None:
    """A trigger on a face the die never shows changes nothing.

    The same record triggered by a natural 2 To Wound on a 4+ wound
    target can never fire (2 is a miss), so the math equals the plain
    profile.
    """
    profile = AttackProfile.shooting(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    never = Modifier(
        lands_on=Stage.MAKE_ARMOUR_SAVES,
        move=1,
        trigger=NaturalRoll(face=2, roll=Stage.ROLL_TO_WOUND),
    )
    assert resolve_attack(profile, [never]).p_unsaved == resolve_attack(profile).p_unsaved


def test_modifier_cannot_move_a_rollless_target() -> None:
    """A target that is no die (a RollState) has nothing to move.

    Moving an IMPOSSIBLE save leaves it impossible: no save appears from
    a modifier alone.
    """
    profile = AttackProfile.shooting(
        hit_target=RollState.AUTOMATIC,
        wound_target=RollState.AUTOMATIC,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )
    improve_save = Modifier(lands_on=Stage.MAKE_ARMOUR_SAVES, move=-2)
    assert resolve_attack(profile, [improve_save]).p_unsaved == 1
