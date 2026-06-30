"""Tests for the D6 probability primitives."""

import random

import pytest

from avelorn.core.dice import (
    binomial_distribution,
    binomial_pmf,
    cap_distribution,
    expected_value,
    p_d6_at_least,
    sample,
)


@pytest.mark.parametrize(
    ("target", "expected"),
    [(1, 1.0), (2, 5 / 6), (4, 0.5), (6, 1 / 6), (7, 0.0), (0, 1.0)],
)
def test_p_d6_at_least(target: int, expected: float) -> None:
    """Single-die probabilities match the face counts."""
    assert p_d6_at_least(target) == pytest.approx(expected)


def test_binomial_pmf_golden_values() -> None:
    """PMF matches hand-computed values."""
    assert binomial_pmf(0, 3, 0.5) == pytest.approx(0.125)
    assert binomial_pmf(2, 2, 1 / 3) == pytest.approx(1 / 9)
    assert binomial_pmf(0, 0, 0.7) == pytest.approx(1.0)


def test_binomial_distribution_sums_to_one() -> None:
    """A full PMF is a probability distribution."""
    distribution = binomial_distribution(10, 2 / 9)
    assert len(distribution) == 11
    assert sum(distribution) == pytest.approx(1.0)


def test_expected_value_matches_n_times_p() -> None:
    """E[Binomial(n, p)] = n * p."""
    assert expected_value(binomial_distribution(12, 0.25)) == pytest.approx(3.0)


def test_cap_distribution_folds_tail_onto_cap() -> None:
    """Mass at or above the cap collapses onto the cap; total is preserved."""
    distribution = binomial_distribution(5, 0.5)
    capped = cap_distribution(distribution, 2)
    assert len(capped) == 3
    assert capped[:2] == pytest.approx(distribution[:2])
    assert capped[2] == pytest.approx(sum(distribution[2:]))
    assert sum(capped) == pytest.approx(1.0)


def test_cap_distribution_no_op_when_cap_exceeds_support() -> None:
    """A cap the outcome can never reach returns the distribution unchanged."""
    distribution = binomial_distribution(3, 0.5)
    assert cap_distribution(distribution, 3) == distribution
    assert cap_distribution(distribution, 10) == distribution


def test_cap_distribution_zero_cap_is_certain_zero() -> None:
    """Capping at zero means zero outcomes with certainty."""
    capped = cap_distribution(binomial_distribution(4, 0.5), 0)
    assert capped == pytest.approx([1.0])


def test_cap_distribution_rejects_negative_cap() -> None:
    """A negative ceiling is meaningless."""
    with pytest.raises(ValueError, match="cap must be >= 0"):
        cap_distribution([0.5, 0.5], -1)


def test_sample_is_reproducible_with_seeded_rng() -> None:
    """The same seed draws the same outcome."""
    distribution = binomial_distribution(10, 0.5)
    first = sample(distribution, random.Random(42))
    second = sample(distribution, random.Random(42))
    assert first == second


def test_sample_respects_support() -> None:
    """Draws never land on zero-probability outcomes."""
    rng = random.Random(7)
    assert all(sample([0.0, 0.0, 1.0], rng) == 2 for _ in range(50))
    draws = [sample(binomial_distribution(3, 0.5), rng) for _ in range(200)]
    assert all(0 <= draw <= 3 for draw in draws)
