"""Tests for the Distribution monad: the laws, the operators, and the reductions."""

from collections.abc import Hashable, Mapping
from fractions import Fraction

import pytest

from avelorn.core.dice import binomial_distribution, cap_distribution, group_distribution
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


# A distribution over per-class count vectors, the shape the multinomial
# aggregation produces: (wounds, instant kills) for one attack.
_classes: Distribution[tuple[int, int]] = Distribution({(1, 0): 0.3, (0, 1): 0.1, (0, 0): 0.6})


def test_add_concatenates_tuple_outcomes_rather_than_summing_them() -> None:
    """``+`` means the outcome type's ``+``, which for a tuple is not a total.

    Pinned because it is silent: a vector of per-class counts added this way
    grows longer instead of adding component-wise, and nothing raises.
    """
    assert all(len(outcome) == 4 for outcome in (_classes + _classes).mass)
    assert all(len(outcome) == 6 for outcome in (3 @ _classes).mass)


def test_combine_adds_count_vectors_component_wise() -> None:
    """The escape hatch: name the component-wise operation and combine on it."""
    summed = _classes.combine(_classes, lambda a, b: (a[0] + b[0], a[1] + b[1]))
    assert summed.total() == pytest.approx(1.0)
    assert all(len(outcome) == 2 for outcome in summed.mass)
    assert summed.mass[(2, 0)] == pytest.approx(0.09)  # both drew a plain wound
    assert summed.mass[(1, 1)] == pytest.approx(2 * 0.3 * 0.1)  # one of each, either order


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


@pytest.mark.parametrize("cap", [0, 1, 3, 6, 9])
def test_map_caps_a_count_without_an_operator_of_its_own(cap: int) -> None:
    """A ceiling is ``min``, which has no operator, and ``map`` already applies it.

    So the wound-to-casualty pipeline needs no further API: group with ``//``,
    cap with ``map``.
    """
    pmf = [0.05, 0.1, 0.15, 0.2, 0.25, 0.15, 0.1]
    assert _same(
        Distribution.from_counts(pmf).map(lambda k: min(k, cap)),
        Distribution.from_counts(cap_distribution(pmf, cap)),
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


def test_only_count_at_distribution_is_defined() -> None:
    """The other spellings stay TypeErrors, so repeat cannot be read as scaling.

    ``dist @ n`` has no meaning, ``dist @ dist`` no obvious one, and ``*`` is
    left undefined rather than guessing which of the two it should be. ``ty``
    rejects all three statically; these assert the runtime refusal too, so
    defining one of them later cannot pass silently.
    """
    for operand in (3, _coin):
        with pytest.raises(TypeError):
            _ = _coin @ operand  # ty: ignore[unsupported-operator]
    with pytest.raises(TypeError):
        _ = _coin * 3  # ty: ignore[unsupported-operator]


def test_matmul_conserves_mass() -> None:
    """Repeated convolution is still a distribution."""
    assert (6 @ _coin).total() == pytest.approx(1.0)


def test_matmul_matches_the_binomial_it_should_defer_to() -> None:
    """The closed form and the repeat agree, which is what makes preferring it safe."""
    assert _same(12 @ _coin, Distribution.from_counts(binomial_distribution(12, 0.5)))


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


# The folds accumulate from the integer 0 and `pure` is the integer 1, so they
# carry whatever numeric type the masses are. These pin that: the `ty: ignore`s
# are the annotation gap (`mass` still says float), not a runtime one.
_SIXTH = Fraction(1, 6)
_exact: Distribution[int] = Distribution({0: _SIXTH * 5, 1: _SIXTH})  # ty: ignore[invalid-argument-type, invalid-assignment]


def _halves(k: int) -> Distribution[int]:
    # An exact step: a fair split, in Fractions.
    return Distribution({k: Fraction(1, 2), k + 1: Fraction(1, 2)})  # ty: ignore[invalid-argument-type, invalid-return-type]


def test_bind_keeps_exact_masses_exact() -> None:
    """An exact distribution through an exact step stays exact, and sums to exactly 1."""
    folded = _exact.bind(_halves)
    assert all(isinstance(p, Fraction) for p in folded.mass.values())
    assert folded.mass == {0: Fraction(5, 12), 1: Fraction(1, 2), 2: Fraction(1, 12)}
    assert folded.total() == 1  # exactly, not to tolerance


def test_map_keeps_exact_masses_exact() -> None:
    """Relabelling merges exact masses without rounding them."""
    merged = _exact.map(lambda k: k % 2)
    assert merged.mass == {0: Fraction(5, 6), 1: _SIXTH}


def test_pure_is_the_identity_for_exact_masses() -> None:
    """Right identity holds exactly, which the old float seed broke."""
    assert _exact.bind(Distribution.pure).mass == _exact.mass


def test_deep_exact_chain_never_drifts() -> None:
    """Ten folds deep, the total is still exactly 1 rather than 1.0000000000000002."""
    walked = _exact
    for _ in range(10):
        walked = walked.bind(_halves)
    assert walked.total() == 1
    assert all(isinstance(p, Fraction) for p in walked.mass.values())


def test_operators_keep_exact_masses_exact() -> None:
    """The arithmetic operators inherit the fix, being written on bind and map."""
    assert all(isinstance(p, Fraction) for p in (_exact + _exact).mass.values())
    assert (3 @ _exact).total() == 1  # exactly; the float seed gave 1.0000000000000002
    assert ((_exact + 2) // 2).total() == 1


def test_pure_carries_an_integer_one() -> None:
    """The identity is int 1, so it coerces neither float nor Fraction masses."""
    assert type(Distribution.pure("x").mass["x"]) is int
