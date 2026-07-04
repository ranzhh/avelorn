"""Tests for the querying layer over combat distributions."""

import pytest

from avelorn.tow.combat.melee import FightResult
from avelorn.tow.combat.query import (
    Comparator,
    Distribution,
    Predicate,
    evaluate,
    fight_distributions,
    query_result,
    result_distributions,
)
from avelorn.tow.combat.shooting import shoot

# A small hand-checkable PMF: P(0)=0.1, P(1)=0.4, P(2)=0.3, P(3)=0.2.
_PMF = (0.1, 0.4, 0.3, 0.2)
_DIST = Distribution("demo", _PMF)


def test_distribution_operators_are_exact() -> None:
    """Each operator reduces the PMF to the hand-computed mass."""
    assert _DIST.exactly(1) == pytest.approx(0.4)
    assert _DIST.at_most(1) == pytest.approx(0.5)
    assert _DIST.at_least(2) == pytest.approx(0.5)
    assert _DIST.between(1, 2) == pytest.approx(0.7)
    assert _DIST.mean() == pytest.approx(0.1 * 0 + 0.4 * 1 + 0.3 * 2 + 0.2 * 3)
    assert _DIST.mode() == 1


def test_distribution_queries_outside_support_are_well_defined() -> None:
    """Outcomes past the support carry zero mass, so the tails saturate."""
    assert _DIST.exactly(9) == 0.0
    assert _DIST.exactly(-1) == 0.0
    assert _DIST.at_most(-1) == 0.0
    assert _DIST.at_most(9) == pytest.approx(1.0)
    assert _DIST.at_least(0) == pytest.approx(1.0)
    assert _DIST.at_least(9) == 0.0


def test_mode_breaks_ties_low() -> None:
    """A flat PMF reports the lowest maximal index."""
    assert Distribution("flat", (0.25, 0.25, 0.25, 0.25)).mode() == 0


def test_mode_undefined_for_empty_distribution() -> None:
    """Mode has no answer with no outcomes; it says so rather than crashing raw."""
    with pytest.raises(ValueError, match="empty distribution"):
        Distribution("empty", ()).mode()


@pytest.mark.parametrize(
    ("op", "value", "upper", "expected"),
    [
        (Comparator.AT_MOST, 1, None, 0.5),
        (Comparator.AT_LEAST, 2, None, 0.5),
        (Comparator.EXACTLY, 2, None, 0.3),
        (Comparator.BETWEEN, 1, 2, 0.7),
    ],
)
def test_evaluate_routes_each_comparator(
    op: Comparator, value: int, upper: int | None, expected: float
) -> None:
    """Evaluate dispatches every comparator to the matching operator."""
    assert evaluate(_DIST, Predicate(op, value, upper)) == pytest.approx(expected)


def test_between_requires_upper_bound() -> None:
    """A BETWEEN predicate without an upper bound is rejected at construction."""
    with pytest.raises(ValueError, match="BETWEEN requires an upper bound"):
        Predicate(Comparator.BETWEEN, 1)


def test_upper_bound_rejected_for_non_between() -> None:
    """An upper bound on a non-interval predicate is a construction error."""
    with pytest.raises(ValueError, match="upper is only valid for BETWEEN"):
        Predicate(Comparator.AT_MOST, 1, 3)


def test_between_rejects_inverted_bounds() -> None:
    """The interval's upper bound must not fall below its lower bound."""
    with pytest.raises(ValueError, match="must be >="):
        Predicate(Comparator.BETWEEN, 3, 1)


def test_negative_threshold_rejected() -> None:
    """A negative threshold is meaningless for a count."""
    with pytest.raises(ValueError, match="value must be >= 0"):
        Predicate(Comparator.AT_MOST, -1)


def test_result_distributions_exposes_wounds_and_casualties() -> None:
    """An uncapped result exposes wounds and casualties, but not survivors."""
    result = shoot(3, ballistic_skill=4, strength=3, toughness=3, armour_value=5)
    distributions = result_distributions(result)
    assert set(distributions) == {"wounds", "casualties"}
    assert distributions["wounds"].pmf == tuple(result.distribution)
    assert distributions["casualties"].pmf == tuple(result.casualties)


def test_survivors_is_the_mirror_of_casualties_over_unit_size() -> None:
    """P(survivors == s) equals P(casualties == size - s), padded to 0..size.

    10 shots into a 2-model unit: casualties cap at 2, so survivors range
    over 0..2 and P(2 survive) == P(0 die).
    """
    result = shoot(10, ballistic_skill=4, strength=3, toughness=3, targets=2)
    survivors = result_distributions(result)["survivors"]
    assert len(survivors.pmf) == 3
    assert survivors.exactly(2) == pytest.approx(result.casualties[0])
    assert survivors.exactly(0) == pytest.approx(result.casualties[2])
    assert sum(survivors.pmf) == pytest.approx(1.0)


def test_survivors_pads_when_volley_cannot_reach_unit_size() -> None:
    """A volley too small to fill the cap leaves high survivor counts certain.

    3 shots into 20 models can remove at most 3, so survivors is supported
    over 17..20 and P(at most 16 survive) is zero.
    """
    result = shoot(3, ballistic_skill=4, strength=3, toughness=3, targets=20)
    survivors = result_distributions(result)["survivors"]
    assert len(survivors.pmf) == 21
    assert survivors.at_most(16) == 0.0
    assert survivors.exactly(20) == pytest.approx(result.casualties[0])
    assert sum(survivors.pmf) == pytest.approx(1.0)


def test_query_result_answers_at_most_survive() -> None:
    """The headline question: P(at most k survive) via the convenience entry point.

    Survivors >= size - shots always, and here equals P(at least size-k die).
    """
    result = shoot(10, ballistic_skill=4, strength=3, toughness=3, targets=5)
    p = query_result(result, "survivors", Predicate(Comparator.AT_MOST, 3))

    # Independent golden: per shot p_unsaved = (4/6)*(1/2) = 1/3 (no save, no
    # ward). "<=3 of 5 survive" == ">=2 of 10 shots wound" == 1 - P(0) - P(1),
    # and the cap at 5 does not touch the 0- and 1-wound masses.
    expected = 1 - (2 / 3) ** 10 - 10 * (1 / 3) * (2 / 3) ** 9
    assert p == pytest.approx(expected)

    casualties = result_distributions(result)["casualties"]
    assert p == pytest.approx(casualties.at_least(2))  # <=3 survive <=> >=2 of 5 die


def test_query_result_rejects_unavailable_variable() -> None:
    """Asking for survivors on an uncapped result names the available variables."""
    result = shoot(3, ballistic_skill=4, strength=3, toughness=3)
    with pytest.raises(KeyError, match="survivors"):
        query_result(result, "survivors", Predicate(Comparator.AT_MOST, 3))


def test_fight_distributions_expose_per_side_counts() -> None:
    """A fight's joint losses surface as per-side casualty and survivor PMFs.

    Joint over (a_lost, b_lost) for 1 fighter each; marginals are
    a_casualties = (0.8, 0.2), b_casualties = (0.85, 0.15), and survivors
    mirror them over each side's size of 1.
    """
    result = FightResult(losses=[[0.7, 0.1], [0.15, 0.05]], first_striker=None)
    dists = fight_distributions(result)
    assert set(dists) == {"a_casualties", "a_survivors", "b_casualties", "b_survivors"}
    assert dists["a_casualties"].pmf == pytest.approx((0.8, 0.2))
    assert dists["a_survivors"].pmf == pytest.approx((0.2, 0.8))  # mirror of casualties
    assert dists["b_casualties"].pmf == pytest.approx((0.85, 0.15))
    # Queried the same way as shooting: P(B loses its whole model).
    assert evaluate(dists["b_survivors"], Predicate(Comparator.EXACTLY, 0)) == pytest.approx(0.15)
