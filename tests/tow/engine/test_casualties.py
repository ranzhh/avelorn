"""Remove Casualties tests: per-attack probabilities to distributions."""

from fractions import Fraction

import pytest

from avelorn.core.dice import binomial_distribution, cap_distribution, group_distribution
from avelorn.core.distribution import Distribution
from avelorn.tow.engine.casualties import (
    AttackBatch,
    _remove_casualties,
    batched_wound_and_casualties,
    wound_and_casualties,
)


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
        p_unsaved=Fraction(1, 3),
        p_kill=p_kill,
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


def test_batched_fold_convolves_independent_batches() -> None:
    """Two one-attack batches' unsaved wounds add: the counts convolve."""
    distribution, casualties = batched_wound_and_casualties(
        [AttackBatch(1, 0.5, 0.0), AttackBatch(1, 0.5, 0.0)],
        wounds_per_model=1,
        targets=None,
    )
    assert distribution == pytest.approx([0.25, 0.5, 0.25])
    assert casualties == pytest.approx([0.25, 0.5, 0.25])


def test_batched_fold_pools_wounds_before_felling_a_multi_wound_model() -> None:
    """2 wounds from one batch and 1 from another fell a whole 3-Wound model.

    The load-bearing subtlety (#46): the fold to models must run on the
    combined wound count, never per batch -- 2//3 + 1//3 would fell none.
    """
    _, casualties = batched_wound_and_casualties(
        [AttackBatch(2, 1.0, 0.0), AttackBatch(1, 1.0, 0.0)],
        wounds_per_model=3,
        targets=1,
    )
    assert casualties == pytest.approx([0.0, 1.0])


def test_batched_fold_with_one_batch_matches_the_single_batch_path() -> None:
    """A lone batch resolves exactly as wound_and_casualties always has."""
    expected = wound_and_casualties(6, p_unsaved=0.3, p_kill=0.1, wounds_per_model=2, targets=4)
    folded = batched_wound_and_casualties(
        [AttackBatch(6, 0.3, 0.1)], wounds_per_model=2, targets=4
    )
    assert folded[0] == pytest.approx(expected[0])
    assert folded[1] == pytest.approx(expected[1])


def test_batched_fold_counts_instant_kills_per_model_across_batches() -> None:
    """A kill removes a whole model; plain wounds pool separately across batches."""
    # One certain kill in one batch, one certain plain wound in the other:
    # against 2-Wound models that is one model slain outright plus a wound
    # carried, never two models.
    _, casualties = batched_wound_and_casualties(
        [AttackBatch(1, 1.0, 1.0), AttackBatch(1, 1.0, 0.0)],
        wounds_per_model=2,
        targets=2,
    )
    assert casualties == pytest.approx([0.0, 1.0, 0.0])


def test_a_wound_worth_the_model_fells_one_per_wound() -> None:
    """Multiple Wounds (2) against 2-Wound models: every unsaved wound fells one.

    Two attacks at p = 1/2: the casualty distribution IS the wound
    distribution — where the plain pool needs two wounds per model
    (P(1 model) = P(2 wounds) = 1/4).
    """
    half = Fraction(1, 2)
    two = Distribution.pure(2)
    distribution, casualties = wound_and_casualties(
        2, p_unsaved=half, p_kill=0, wounds_per_model=2, targets=None, damage=two
    )
    assert distribution == [Fraction(1, 4), half, Fraction(1, 4)]
    assert casualties == [Fraction(1, 4), half, Fraction(1, 4)]
    _, pooled = wound_and_casualties(2, p_unsaved=half, p_kill=0, wounds_per_model=2, targets=None)
    assert pooled == [Fraction(3, 4), Fraction(1, 4)]


def test_a_dice_multiplier_rolls_separately_per_wound() -> None:
    """Multiple Wounds (D3) against 3-Wound models: the per-wound die, enumerated.

    Two certain wounds, each rolling a D3 against a fresh or damaged model:
    of the nine (d1, d2) pairs only (3, 3) fells two, and only (1, 1) fells
    none — leaving the other seven to fell exactly one (7/9).
    """
    d3 = Distribution({1: Fraction(1, 3), 2: Fraction(1, 3), 3: Fraction(1, 3)})
    _, casualties = wound_and_casualties(
        2, p_unsaved=Fraction(1), p_kill=0, wounds_per_model=3, targets=None, damage=d3
    )
    assert casualties == [Fraction(1, 9), Fraction(7, 9), Fraction(1, 9)]


def test_excess_wounds_do_not_spill_over() -> None:
    """Damage past the model's Wounds is discarded: 5 wounds fell one 3-Wound model each."""
    _, casualties = wound_and_casualties(
        2,
        p_unsaved=Fraction(1),
        p_kill=0,
        wounds_per_model=3,
        targets=None,
        damage=Distribution.pure(5),
    )
    assert casualties == [0, 0, 1]


def test_batched_fold_pools_a_shared_multiplier_with_kills_additive() -> None:
    """Two certain-wound batches share a multiplier; an instant kill adds a model.

    One batch's wound carries the kill class instead: the kill removes a
    model outright while the other batch's multiplied wound fells its own.
    """
    two = Distribution.pure(2)
    batches = [
        AttackBatch(1, p_unsaved=Fraction(1), p_kill=Fraction(0)),
        AttackBatch(1, p_unsaved=Fraction(1), p_kill=Fraction(1)),
    ]
    distribution, casualties = batched_wound_and_casualties(
        batches, wounds_per_model=2, targets=None, damage=two
    )
    assert distribution == [0, 0, 1]
    assert casualties == [0, 0, 1]
