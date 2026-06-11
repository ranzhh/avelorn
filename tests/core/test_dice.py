"""Tests for the D6 probability primitives."""

import pytest

from avelorn.core.dice import binomial_distribution, binomial_pmf, expected_value, p_d6_at_least


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
