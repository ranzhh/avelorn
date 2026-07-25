"""Tests for the Distribution monad: the laws, and the reductions."""

from collections.abc import Hashable, Mapping

import pytest

from avelorn.core.distribution import Distribution


def _same[T: Hashable](a: Distribution[T], b: Distribution[T]) -> bool:
    """Whether two distributions carry the same mass, to floating tolerance.

    Returns:
        True if every outcome's mass matches within tolerance.
    """
    keys = set(a.mass) | set(b.mass)
    return all(a.mass.get(k, 0.0) == pytest.approx(b.mass.get(k, 0.0)) for k in keys)


# A coin and a couple of arrows to exercise the laws with.
_coin: Distribution[int] = Distribution({0: 0.5, 1: 0.5})


def _step(k: int) -> Distribution[int]:
    # k -> a small spread around it, so bind has something to mix.
    return Distribution({k: 0.75, k + 1: 0.25})


def _other(k: int) -> Distribution[str]:
    return Distribution({f"<{k}>": 1.0})


def test_left_identity() -> None:
    """pure(a).bind(f) == f(a)."""
    assert _same(Distribution.pure(3).bind(_step), _step(3))


def test_right_identity() -> None:
    """m.bind(pure) == m."""
    assert _same(_coin.bind(Distribution.pure), _coin)


def test_associativity() -> None:
    """m.bind(f).bind(g) == m.bind(lambda x: f(x).bind(g))."""
    left = _coin.bind(_step).bind(_other)
    right = _coin.bind(lambda k: _step(k).bind(_other))
    assert _same(left, right)


def test_bind_mixes_by_probability() -> None:
    """A hand-computed mix: 0.5*{0,1} then each k -> {k:.75, k+1:.25}."""
    mixed = _coin.bind(_step)
    assert mixed.mass[0] == pytest.approx(0.375)  # 0.5 * 0.75
    assert mixed.mass[1] == pytest.approx(0.5)  # 0.5*0.25 + 0.5*0.75
    assert mixed.mass[2] == pytest.approx(0.125)  # 0.5 * 0.25
    assert mixed.total() == pytest.approx(1.0)


def test_map_merges_collisions() -> None:
    """Relabelling that collapses outcomes sums their mass."""
    parity = Distribution({0: 0.2, 1: 0.3, 2: 0.5}).map(lambda k: k % 2)
    assert parity.mass[0] == pytest.approx(0.7)  # 0 and 2
    assert parity.mass[1] == pytest.approx(0.3)


def test_from_counts_round_trips_a_pmf() -> None:
    """A count-pmf lifts to integer outcomes, dropping zero mass."""
    dist = Distribution.from_counts([0.0, 0.25, 0.75])
    assert dist.mass == {1: 0.25, 2: 0.75}


def test_prob_and_expect_over_counts() -> None:
    """Predicate queries reduce to prob; the mean to expect."""
    dist = Distribution.from_counts([0.1, 0.2, 0.3, 0.4])
    assert dist.prob(lambda k: k >= 2) == pytest.approx(0.7)
    assert dist.prob(lambda k: k == 0) == pytest.approx(0.1)
    assert dist.expect(float) == pytest.approx(0.1 * 0 + 0.2 + 0.3 * 2 + 0.4 * 3)


def test_mass_is_a_mapping() -> None:
    """The carried mass is a plain mapping — no engine coupling."""
    assert isinstance(Distribution.pure("x").mass, Mapping)
