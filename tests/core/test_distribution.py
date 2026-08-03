"""Tests for the Distribution monad: the laws, the operators, and the reductions."""

from collections.abc import Hashable, Mapping

import pytest

from avelorn.core.dice import binomial_distribution, group_distribution
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


def test_add_convolves_two_distributions() -> None:
    """Two independent coins summed: the count of heads over two throws."""
    assert _same(_coin + _coin, Distribution({0: 0.25, 1: 0.5, 2: 0.25}))


def test_add_is_combine_with_addition() -> None:
    """The operator is the lift, not a second implementation."""
    assert _same(_coin + _coin, _coin.combine(_coin, lambda a, b: a + b))


def test_add_shifts_every_outcome_by_a_constant() -> None:
    """A bare outcome on either side moves the whole distribution."""
    shifted = Distribution({0: 0.25, 1: 0.75}) + 3
    assert _same(shifted, Distribution({3: 0.25, 4: 0.75}))
    assert _same(3 + Distribution({0: 0.25, 1: 0.75}), shifted)


def test_radd_keeps_the_constant_on_the_left() -> None:
    """``value + dist`` puts the constant first, for a non-commutative ``+``."""
    assert _same("<" + Distribution.pure("x"), Distribution.pure("<x"))


def test_add_conserves_mass() -> None:
    """Convolution is still a distribution."""
    assert (_coin + _coin + _coin).total() == pytest.approx(1.0)


def test_sub_gives_a_signed_difference() -> None:
    """Two coins differenced span -1 to 1, the middle carrying both ties."""
    assert _same(_coin - _coin, Distribution({-1: 0.25, 0: 0.5, 1: 0.25}))


def test_sub_takes_operands_in_written_order() -> None:
    """``a - b`` and ``b - a`` are mirror images, not the same distribution."""
    ahead = Distribution({2: 1.0}) - _coin
    behind = _coin - Distribution({2: 1.0})
    assert _same(ahead, Distribution({1: 0.5, 2: 0.5}))
    assert _same(behind, Distribution({-2: 0.5, -1: 0.5}))


def test_rsub_subtracts_the_distribution_from_the_constant() -> None:
    """``value - dist`` reads as written, not reversed."""
    assert _same(10 - _coin, Distribution({9: 0.5, 10: 0.5}))


def test_rsub_mirrors_casualties_into_survivors() -> None:
    """``size - casualties`` is the operator's plainest use, and correlation-free."""
    casualties = Distribution.from_counts([0.1, 0.2, 0.3, 0.4])
    survivors = 5 - casualties
    assert _same(survivors, Distribution({5: 0.1, 4: 0.2, 3: 0.3, 2: 0.4}))
    assert survivors.expect(float) == pytest.approx(5 - casualties.expect(float))


def test_floordiv_groups_outcomes_into_whole_units() -> None:
    """Wounds into 3-Wound models: 0-2 leave none dead, 3-5 leave one."""
    wounds = Distribution({0: 0.1, 1: 0.2, 2: 0.1, 3: 0.3, 4: 0.2, 6: 0.1})
    assert _same(wounds // 3, Distribution({0: 0.4, 1: 0.5, 2: 0.1}))


def test_floordiv_by_one_changes_nothing() -> None:
    """1-Wound models are the degenerate case, as they are in the engine."""
    wounds = Distribution({0: 0.25, 1: 0.5, 2: 0.25})
    assert _same(wounds // 1, wounds)


@pytest.mark.parametrize("group_size", [1, 2, 3, 4])
def test_floordiv_matches_the_count_pmf_grouping(group_size: int) -> None:
    """The operator agrees with ``group_distribution`` on the same fold."""
    pmf = [0.05, 0.1, 0.15, 0.2, 0.25, 0.15, 0.1]
    assert _same(
        Distribution.from_counts(pmf) // group_size,
        Distribution.from_counts(group_distribution(pmf, group_size)),
    )


def test_floordiv_conserves_mass() -> None:
    """Grouping redistributes mass, it does not lose any."""
    assert (Distribution.from_counts([0.05, 0.1, 0.15, 0.2, 0.25, 0.15, 0.1]) // 3).total() == (
        pytest.approx(1.0)
    )


@pytest.mark.parametrize("group_size", [0, -1])
def test_floordiv_rejects_a_group_size_below_one(group_size: int) -> None:
    """No group to count, and the same refusal ``group_distribution`` makes."""
    with pytest.raises(ValueError, match="group_size must be >= 1"):
        _ = _coin // group_size


def test_matmul_sums_independent_copies() -> None:
    """``4 @ coin`` is Binomial(4, 0.5) — four throws totalled."""
    assert _same(4 @ _coin, Distribution.from_counts(binomial_distribution(4, 0.5)))


def test_matmul_of_one_copy_is_the_distribution() -> None:
    """One copy adds nothing to sum."""
    assert _same(1 @ _coin, _coin)


def test_matmul_is_repeated_addition() -> None:
    """The repeat is the operator it is built from, applied n - 1 times."""
    assert _same(3 @ _coin, _coin + _coin + _coin)


def test_matmul_is_not_scaling_the_outcomes() -> None:
    """Three draws totalled is not one draw tripled — the trap ``*`` would set."""
    assert not _same(3 @ _coin, _coin.map(lambda k: k * 3))


def test_matmul_rejects_no_copies() -> None:
    """Zero copies has no identity to return for a general outcome type."""
    with pytest.raises(ValueError, match="copies must be >= 1"):
        _ = 0 @ _coin


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
