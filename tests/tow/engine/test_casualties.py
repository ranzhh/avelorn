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


@pytest.mark.parametrize("p_kill", [Fraction(0), Fraction(1, 6)])
@pytest.mark.parametrize(
    ("n", "wounds_per_model", "targets"),
    [
        (4, 2, 4),  # every casualty index reachable
        (2, 3, 5),  # only 0..2 reachable: a volley too small to fill the unit
    ],
)
def test_exact_probabilities_survive_both_aggregation_paths(
    p_kill: Fraction, n: int, wounds_per_model: int, targets: int
) -> None:
    """An exact per-attack probability aggregates exactly, kills or no kills.

    Both branches: the binomial path when nothing instant-kills, and the
    multinomial one when something does. Both a config where every casualty index
    is reachable and one where the upper indices are not, since an accumulator
    seeded with the wrong kind of zero only shows up at an index nothing lands
    on. The `ty: ignore`s are the annotation gap — these signatures still say
    `float`.
    """
    wounds, casualties = wound_and_casualties(
        n,
        p_unsaved=Fraction(1, 3),  # ty: ignore[invalid-argument-type]
        p_kill=p_kill,  # ty: ignore[invalid-argument-type]
        wounds_per_model=wounds_per_model,
        targets=targets,
    )
    assert all(isinstance(p, Fraction) for p in wounds)
    assert all(isinstance(p, Fraction) for p in casualties)
    assert sum(wounds) == 1
    assert sum(casualties) == 1


@pytest.mark.parametrize(
    ("p_wound_only", "p_kill", "kind"),
    [(0.5, 0.25, float), (Fraction(1, 2), Fraction(1, 4), Fraction)],
)
def test_casualty_masses_are_all_one_numeric_type(
    p_wound_only: float, p_kill: float, kind: type
) -> None:
    """Every index carries the callers' own kind of zero, including unreached ones.

    A volley of one cannot fill five casualty counts, so the upper indices are
    never added to. Seeding them with a bare integer would leave a `list[float]`
    holding ints, which anything dispatching on a mass's type would mishandle.
    """
    wounds, casualties = _remove_casualties(
        1,
        p_wound_only=p_wound_only,
        p_kill=p_kill,
        wounds_per_model=1,
        targets=5,
    )
    assert all(isinstance(p, kind) for p in wounds)
    assert all(isinstance(p, kind) for p in casualties)
    assert sum(casualties) == 1
