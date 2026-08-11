"""Tests for the D6 probability primitives."""

import random
from fractions import Fraction

import pytest

from avelorn.core.dice import (
    binomial_distribution,
    binomial_pmf,
    cap_distribution,
    expected_value,
    group_distribution,
    multinomial_outcomes,
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


def test_group_distribution_buckets_by_integer_division() -> None:
    """Outcomes 0..6 grouped by 3: whole groups are 0 (0-2), 1 (3-5), 2 (6)."""
    # index = wounds; value tagged so the fold is easy to verify by hand.
    dist = [0.1, 0.1, 0.1, 0.2, 0.2, 0.1, 0.2]  # sums to 1.0
    grouped = group_distribution(dist, 3)
    assert grouped == pytest.approx([0.3, 0.5, 0.2])  # {0,1,2},{3,4,5},{6}
    assert sum(grouped) == pytest.approx(1.0)


def test_group_distribution_identity_for_size_one() -> None:
    """Grouping by 1 is a no-op copy (one wound per model)."""
    dist = binomial_distribution(4, 0.5)
    grouped = group_distribution(dist, 1)
    assert grouped == dist
    assert grouped is not dist


def test_group_distribution_length_rounds_up() -> None:
    """5 outcomes (0..4) grouped by 3 span buckets 0 and 1."""
    grouped = group_distribution(binomial_distribution(4, 0.5), 3)
    assert len(grouped) == 2  # (5 - 1) // 3 + 1
    assert sum(grouped) == pytest.approx(1.0)


def test_group_distribution_rejects_non_positive_size() -> None:
    """A group size below 1 is meaningless."""
    with pytest.raises(ValueError, match="group_size must be >= 1"):
        group_distribution([0.5, 0.5], 0)


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


def test_multinomial_one_class_reduces_to_binomial() -> None:
    """With a single class, each count's mass is the binomial PMF."""
    masses = {counts[0]: mass for counts, mass in multinomial_outcomes(6, (1 / 3,))}
    for k, mass in masses.items():
        assert mass == pytest.approx(binomial_pmf(k, 6, 1 / 3))
    assert sum(masses.values()) == pytest.approx(1.0)


def test_multinomial_two_classes_sum_to_one_with_golden() -> None:
    """Two-class vectors cover the space; a hand value pins the PMF.

    2 trials at p=(1/2, 1/3): P(one of each) = 2 * 1/2 * 1/3 = 1/3.
    """
    outcomes = dict(multinomial_outcomes(2, (1 / 2, 1 / 3)))
    assert sum(outcomes.values()) == pytest.approx(1.0)
    assert len(outcomes) == 6  # count vectors with n1 + n2 <= 2
    assert outcomes[(1, 1)] == pytest.approx(1 / 3)


def test_multinomial_zero_trials_is_certain_empty() -> None:
    """No trials: one all-zero vector with probability 1."""
    assert dict(multinomial_outcomes(0, (0.5, 0.2))) == {(0, 0): pytest.approx(1.0)}


def test_multinomial_rejects_negative_trials() -> None:
    """A negative trial count is meaningless."""
    with pytest.raises(ValueError, match="trials must be >= 0"):
        list(multinomial_outcomes(-1, (0.5,)))


def test_binomial_carries_an_exact_probability() -> None:
    """An exact p gives exact masses, summing to exactly 1.

    The signatures carry `Probability`, so this is exactness the type system
    permits, not merely tolerates.
    """
    exact = binomial_distribution(4, Fraction(1, 3))
    assert all(isinstance(p, Fraction) for p in exact)
    assert sum(exact) == 1
    assert exact[0] == Fraction(16, 81)  # (2/3)^4


def test_multinomial_carries_an_exact_probability() -> None:
    """The class-count walk stays exact, and its vectors still sum to exactly 1."""
    exact_classes = (Fraction(1, 3), Fraction(1, 6))
    outcomes = list(multinomial_outcomes(3, exact_classes))
    assert all(isinstance(mass, Fraction) for _, mass in outcomes)
    assert sum(mass for _, mass in outcomes) == 1


def test_binomial_float_path_is_unchanged() -> None:
    """A float p gives the same masses as before, to the last bit.

    Hardcoded rather than compared against `binomial_pmf`, which is the function
    whose arithmetic changed: `binomial_distribution` is a comprehension over it,
    so comparing the two would pass whatever either returned. These values are
    the exact binomial at p=1/4 converted to float, and 1/4 and 3/4 are exact in
    binary, so the comparison is bit-for-bit rather than approximate.
    """
    assert binomial_distribution(6, 0.25) == [
        0.177978515625,
        0.35595703125,
        0.296630859375,
        0.1318359375,
        0.032958984375,
        0.00439453125,
        0.000244140625,
    ]
    assert sum(binomial_distribution(6, 0.25)) == pytest.approx(1.0)
