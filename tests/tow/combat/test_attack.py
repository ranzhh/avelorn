"""Attack dice-walk tests.

Exact equivalence with the chart chain, plus transform hooks proven by
test doubles (no shipped rules).
"""

from dataclasses import replace
from fractions import Fraction

import pytest

from avelorn.tow.combat.attack import (
    AttackProfile,
    Outcome,
    RollState,
    RollTarget,
    Transform,
    resolve_attack,
    walk,
)
from avelorn.tow.combat.charts import hit_probability, save_probability, wound_probability
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
        AttackProfile(hit_target=h, wound_target=w, save_target=s, ward_target=ward)
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
    profile = AttackProfile(hit_target=hit_target, wound_target=4, save_target=5, ward_target=6)
    assert sum(p for p, _ in walk(profile)) == Fraction(1)


def test_seven_plus_confirmation_golden() -> None:
    """7+ to hit: a natural 6 confirmed at 4+ -> 1/6 * 1/2 hits (exact)."""
    profile = AttackProfile(
        hit_target=7,
        wound_target=2,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )
    assert resolve_attack(profile).p_unsaved == Fraction(1, 12) * Fraction(5, 6)


# --- Transform hooks, exercised by test doubles (no shipped rules). ---


def _worsen_save_on_natural_six(face: int, profile: AttackProfile) -> AttackProfile:
    # The Armour Bane (1) shape: a natural 6 To Wound improves AP by 1,
    # worsening the save target; past 6+ there is no save at all.
    if face != 6 or not isinstance(profile.save_target, int):
        return profile
    worsened = profile.save_target + 1
    return replace(profile, save_target=worsened if worsened <= 6 else RollState.IMPOSSIBLE)


def test_on_success_double_reproduces_armour_bane_golden() -> None:
    """On a natural 6 To Wound the save worsens; 13/54 is the spike golden.

    Hit 3+, wound 4+, save 5+: 2/3 * (2/6 * 2/3 + 1/6 * 5/6) = 13/54.
    """
    profile = AttackProfile(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    double = Transform(stage=Stage.ROLL_TO_WOUND, on_success=_worsen_save_on_natural_six)
    assert resolve_attack(profile, [double]).p_unsaved == Fraction(13, 54)


def test_modify_targets_double_equals_baked_in_modifier() -> None:
    """A +1-to-hit transform equals the same modifier baked into the target."""
    profile = AttackProfile(
        hit_target=4, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )

    def improve_hit(p: AttackProfile) -> AttackProfile:
        assert isinstance(p.hit_target, int)
        return replace(p, hit_target=p.hit_target - 1)

    plus_one = Transform(stage=Stage.ROLL_TO_HIT, modify_targets=improve_hit)
    baked = replace(profile, hit_target=3)
    assert resolve_attack(profile, [plus_one]).p_unsaved == resolve_attack(baked).p_unsaved


def test_transforms_apply_in_priority_order() -> None:
    """Set-to and shift compose by ascending priority, not list position."""
    profile = AttackProfile(
        hit_target=2, wound_target=2, save_target=5, ward_target=RollState.IMPOSSIBLE
    )

    def set_to_two(priority: int) -> Transform:
        return Transform(
            stage=Stage.MAKE_ARMOUR_SAVES,
            priority=priority,
            modify_targets=lambda p: replace(p, save_target=2),
        )

    def worsen_one(priority: int) -> Transform:
        def worsen(p: AttackProfile) -> AttackProfile:
            target = p.save_target if isinstance(p.save_target, int) else 6
            return replace(p, save_target=target + 1)

        return Transform(stage=Stage.MAKE_ARMOUR_SAVES, priority=priority, modify_targets=worsen)

    p_hit_wound = Fraction(5, 6) * Fraction(5, 6)
    # set(2) first, then +1 -> save on 3+ (fails 2/6).
    first = resolve_attack(profile, [worsen_one(1), set_to_two(0)]).p_unsaved
    assert first == p_hit_wound * Fraction(2, 6)
    # +1 first (5 -> 6), then set(2) -> save on 2+ (fails 1/6).
    second = resolve_attack(profile, [worsen_one(0), set_to_two(1)]).p_unsaved
    assert second == p_hit_wound * Fraction(1, 6)


def test_transforms_absent_leave_walk_unchanged() -> None:
    """An empty transform list is the identity."""
    profile = AttackProfile(hit_target=3, wound_target=4, save_target=5, ward_target=4)
    assert resolve_attack(profile, []).p_unsaved == resolve_attack(profile).p_unsaved
    assert sum(p for p, _ in walk(profile, [])) == Fraction(1)


def _killing_blow(face: int, profile: AttackProfile) -> AttackProfile:
    # The Killing Blow shape: a natural 6 To Wound skips the armour save
    # (Ward Saves attempted as normal) and the unsaved wound removes the
    # model outright.
    if face != 6:
        return profile
    return replace(profile, save_target=RollState.IMPOSSIBLE, unsaved_outcome=Outcome.INSTANT_KILL)


def test_instant_kill_double_reproduces_spike_classes() -> None:
    """Hit 3+, wound 4+, save 5+: classes are none 21/27, wound 4/27, kill 1/9."""
    profile = AttackProfile(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    double = Transform(stage=Stage.ROLL_TO_WOUND, on_success=_killing_blow)
    resolution = resolve_attack(profile, [double])
    assert resolution.p_of(Outcome.INSTANT_KILL) == Fraction(1, 9)
    assert resolution.p_of(Outcome.UNSAVED_WOUND) == Fraction(4, 27)
    assert resolution.p_unsaved == Fraction(1, 9) + Fraction(4, 27)
    assert sum(resolution.outcomes.values()) == Fraction(1)


def test_ward_save_applies_to_instant_kills() -> None:
    """A 5+ ward scales the kill class by its failure chance (4/6)."""
    profile = AttackProfile(hit_target=3, wound_target=4, save_target=5, ward_target=5)
    double = Transform(stage=Stage.ROLL_TO_WOUND, on_success=_killing_blow)
    resolution = resolve_attack(profile, [double])
    assert resolution.p_of(Outcome.INSTANT_KILL) == Fraction(1, 9) * Fraction(4, 6)


def test_outcomes_without_transforms_have_no_kill_class() -> None:
    """The vanilla walk never produces an instant kill."""
    profile = AttackProfile(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    resolution = resolve_attack(profile)
    assert resolution.p_of(Outcome.INSTANT_KILL) == 0
    assert resolution.p_unsaved == Fraction(2, 9)


def test_automatic_success_consumes_no_die() -> None:
    """An automatic wound succeeds without a roll: p_unsaved is p_hit."""
    profile = AttackProfile(
        hit_target=3,
        wound_target=RollState.AUTOMATIC,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )
    assert resolve_attack(profile).p_unsaved == Fraction(4, 6)
    assert sum(p for p, _ in walk(profile)) == Fraction(1)


def test_automatic_hit_skips_the_natural_one() -> None:
    """An automatic hit has no die, so not even a natural 1 fails it."""
    profile = AttackProfile(
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
    profile = AttackProfile(
        hit_target=3,
        wound_target=RollState.AUTOMATIC,
        save_target=5,
        ward_target=RollState.IMPOSSIBLE,
    )
    double = Transform(stage=Stage.ROLL_TO_WOUND, on_success=_killing_blow)
    resolution = resolve_attack(profile, [double])
    assert resolution.p_of(Outcome.INSTANT_KILL) == 0
    assert resolution.p_of(Outcome.UNSAVED_WOUND) == Fraction(4, 6) * Fraction(4, 6)


def test_wound_modifier_cannot_defeat_the_natural_one() -> None:
    """A transform driving the wound target to 1 still fails on a natural 1.

    "Rolls of a Natural 1" (p.140): a roll To Wound of a natural 1 is
    always a fail, regardless of modifiers. A "+1 to wound" against a
    2+ target must yield 5/6, not 6/6.
    """
    profile = AttackProfile(
        hit_target=RollState.AUTOMATIC,
        wound_target=2,
        save_target=RollState.IMPOSSIBLE,
        ward_target=RollState.IMPOSSIBLE,
    )

    def improve_wound(p: AttackProfile) -> AttackProfile:
        assert isinstance(p.wound_target, int)
        return replace(p, wound_target=p.wound_target - 1)

    plus_one = Transform(stage=Stage.ROLL_TO_WOUND, modify_targets=improve_wound)
    assert resolve_attack(profile, [plus_one]).p_unsaved == Fraction(5, 6)
