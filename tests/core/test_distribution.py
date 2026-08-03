"""Tests for the Distribution monad: the laws, the operators, and the reductions."""

from collections.abc import Hashable, Mapping

import pytest

from avelorn.core.distribution import Distribution, Step


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


def _spread(k: int) -> Distribution[int]:
    # One step of a random walk: k -> {k, k+1} with equal mass.
    return Distribution({k: 0.5, k + 1: 0.5})


def test_deep_chaining_stays_normalised_and_flat() -> None:
    """Bind chains to any depth — mass stays 1.0 and outcomes never nest."""
    chained = Distribution.pure(0).bind(_spread).bind(_spread).bind(_spread).bind(_spread)
    assert chained.total() == pytest.approx(1.0)
    assert all(isinstance(outcome, int) for outcome in chained.mass)  # flat, not nested
    # Four chained steps of {+0, +1} from 0 is Binomial(4, 0.5): P(2) = 6/16.
    assert chained.mass[2] == pytest.approx(0.375)


def test_mass_is_a_mapping() -> None:
    """The carried mass is a plain mapping — no engine coupling."""
    assert isinstance(Distribution.pure("x").mass, Mapping)


def test_combine_takes_the_joint_of_two_independent_variables() -> None:
    """Two coins paired give four equally likely ordered pairs."""
    paired = _coin.combine(_coin, lambda a, b: (a, b))
    assert paired.total() == pytest.approx(1.0)
    assert all(
        paired.mass[pair] == pytest.approx(0.25) for pair in ((0, 0), (0, 1), (1, 0), (1, 1))
    )


def test_combine_merges_pairs_its_op_cannot_tell_apart() -> None:
    """Summing two coins collapses the two one-each pairs into a single outcome."""
    assert _same(
        _coin.combine(_coin, lambda a, b: a + b), Distribution({0: 0.25, 1: 0.5, 2: 0.25})
    )


def test_combine_keeps_operand_order() -> None:
    """``op`` sees this distribution's draw first, so a non-commutative op is safe."""
    left = Distribution.pure("a")
    right = Distribution.pure("b")
    assert _same(left.combine(right, lambda a, b: a + b), Distribution.pure("ab"))


def test_rshift_is_bind() -> None:
    """``dist >> step`` is spelling for bind, not a second fold."""
    assert _same(_coin >> _step, _coin.bind(_step))


def test_rshift_chains_left_to_right() -> None:
    """Chained ``>>`` resolves in written order, like the bind chain it spells."""
    assert _same(_coin >> _step >> _other, _coin.bind(_step).bind(_other))


def test_step_is_callable_and_binds() -> None:
    """A Step resolves at an outcome, and chains as any callable of its shape."""
    spread = Step(_step)
    assert _same(spread(3), _step(3))
    assert _same(_coin >> spread, _coin.bind(_step))


def test_step_composition_matches_binding_in_sequence() -> None:
    """``a >> b`` as a value resolves the same as binding a then b."""
    composed = Step(_step) >> Step(_other)
    assert _same(_coin >> composed, _coin.bind(_step).bind(_other))


def test_step_composition_is_associative() -> None:
    """Grouping a chain of steps cannot change what it resolves to."""
    a, b, c = Step(_step), Step(_step), Step(_other)
    assert _same(_coin >> ((a >> b) >> c), _coin >> (a >> (b >> c)))


def test_certain_step_lifts_a_relabel() -> None:
    """Step.certain is map's arrow — a deterministic step joins the same chain."""
    parity: Step[int, int] = Step.certain(lambda k: k % 2)
    dist = Distribution({0: 0.2, 1: 0.3, 2: 0.5})
    assert _same(dist >> parity, dist.map(lambda k: k % 2))
