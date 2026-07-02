"""Attack dice-walk tests: exact equivalence with the chart chain."""

from fractions import Fraction

import pytest

from avelorn.tow.combat.attack import AttackProfile, resolve_attack, walk
from avelorn.tow.combat.charts import hit_probability, save_probability, wound_probability

# Every shape the charts can hand the resolver: impossible (0, 10+) and
# clamped (1) hit targets, the 7+ confirmation band, "-" wound rows and
# no-save/no-ward cases included.
_HIT_TARGETS = range(0, 12)
_WOUND_TARGETS = (None, 2, 3, 4, 5, 6)
_SAVE_TARGETS = (None, 1, 2, 5, 6, 7)
_WARD_TARGETS = (None, 4)


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
        hit_probability(profile.hit_target)
        * wound_probability(profile.wound_target)
        * (1.0 - save_probability(profile.save_target))
        * (1.0 - save_probability(profile.ward_target))
    )
    assert float(resolve_attack(profile).p_unsaved) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("hit_target", _HIT_TARGETS)
def test_walk_is_exhaustive(hit_target: int) -> None:
    """Every path is enumerated: the walk's probabilities sum to exactly 1."""
    profile = AttackProfile(hit_target=hit_target, wound_target=4, save_target=5, ward_target=6)
    assert sum(p for p, _ in walk(profile)) == Fraction(1)


def test_seven_plus_confirmation_golden() -> None:
    """7+ to hit: a natural 6 confirmed at 4+ -> 1/6 * 1/2 hits (exact)."""
    profile = AttackProfile(hit_target=7, wound_target=2, save_target=None, ward_target=None)
    assert resolve_attack(profile).p_unsaved == Fraction(1, 12) * Fraction(5, 6)
