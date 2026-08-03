"""Remove Casualties tests: per-attack probabilities to distributions."""

from fractions import Fraction

import pytest

from avelorn.core.dice import binomial_distribution, cap_distribution, group_distribution
from avelorn.tow.engine.casualties import _remove_casualties, wound_and_casualties


def test_remove_casualties_with_no_kill_mass_matches_binomial_path() -> None:
    """The class-aware fold degenerates to binomial -> group -> cap."""
    p = 2 / 9
    distribution, casualties = _remove_casualties(
        10, p_wound_only=p, p_kill=0.0, wounds_per_model=3, targets=2
    )
    expected_distribution = binomial_distribution(10, p)
    expected_casualties = cap_distribution(group_distribution(expected_distribution, 3), 2)
    assert distribution == pytest.approx(expected_distribution)
    assert casualties == pytest.approx(expected_casualties)


def test_no_kill_mass_takes_the_binomial_path() -> None:
    """With no instant kills, the public entry matches binomial -> group -> cap."""
    p = 0.3
    distribution, casualties = wound_and_casualties(
        8, p_unsaved=p, p_kill=0.0, wounds_per_model=2, targets=3
    )
    expected = binomial_distribution(8, p)
    assert distribution == pytest.approx(expected)
    assert casualties == pytest.approx(cap_distribution(group_distribution(expected, 2), 3))


def test_uncapped_casualties_when_no_target_size() -> None:
    """Without a target size, casualties are not capped."""
    _, casualties = wound_and_casualties(
        5, p_unsaved=0.5, p_kill=0.0, wounds_per_model=1, targets=None
    )
    assert len(casualties) == 6  # 0..5, uncapped
    assert sum(casualties) == pytest.approx(1.0)


def test_exact_probabilities_survive_both_aggregation_paths() -> None:
    """An exact per-attack probability aggregates exactly, kills or no kills.

    Both branches: the binomial path when nothing instant-kills, and the
    multinomial one when something does. The `ty: ignore`s are the annotation
    gap — these signatures still say `float`.
    """
    for p_kill in (Fraction(0), Fraction(1, 6)):
        wounds, casualties = wound_and_casualties(
            4,
            p_unsaved=Fraction(1, 3),  # ty: ignore[invalid-argument-type]
            p_kill=p_kill,  # ty: ignore[invalid-argument-type]
            wounds_per_model=2,
            targets=4,
        )
        assert all(isinstance(p, Fraction) for p in wounds)
        assert all(isinstance(p, Fraction) for p in casualties)
        assert sum(wounds) == 1
        assert sum(casualties) == 1
