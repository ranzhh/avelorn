"""Tests for fielded sides made of parts."""

from dataclasses import replace

import pytest

from avelorn.core.distribution import Distribution
from avelorn.core.graph import Carrier, Source
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.fielding import Fielding, Part
from avelorn.tow.kernels import Standing, Standings, back_rank, back_rank_multiplied
from avelorn.tow.schema.reference import RuleRef

REPO = TOWRepository()
MANEATERS = REPO.units["maneaters"]


def _maneaters() -> Fielding:
    maneater, captain = MANEATERS.profiles
    return Fielding(
        "maneaters",
        MANEATERS.rank_and_file,
        (Part("maneater", maneater, 3), Part("maneater-captain", captain, 1)),
        4,
    )


@pytest.mark.parametrize(
    ("wounds", "maneaters", "captain"),
    [
        pytest.param(4, Standing(2, 1), Standing(1, 0), id="one-maneater-falls-the-next-is-hurt"),
        pytest.param(9, Standing(0, 0), Standing(1, 0), id="the-rank-and-file-fall-first"),
        pytest.param(11, Standing(0, 0), Standing(1, 2), id="the-captain-is-hurt-last"),
        pytest.param(20, Standing(0, 0), Standing(0, 0), id="wounds-past-the-last-model-are-lost"),
    ],
)
def test_casualties_come_off_the_rank_and_file_before_the_champion(
    wounds: int, maneaters: Standing, captain: Standing
) -> None:
    """The Captain falls last, though placed at the back; a Maneater takes 3 Wounds to fall."""
    side = _maneaters()

    left = back_rank(side.standing(4), wounds, side.removal)

    assert left == Standings((("maneater", maneaters), ("maneater-captain", captain)))


@pytest.mark.parametrize(
    ("wounds", "maneaters", "captain"),
    [
        pytest.param(5, Standing(1, 2), Standing(1, 0), id="two-maneaters-fall-the-excess-lost"),
        pytest.param(7, Standing(0, 0), Standing(1, 2), id="the-captain-is-hurt-last"),
    ],
)
def test_a_multiplied_wound_never_spills_onto_the_next_model(
    wounds: int, maneaters: Standing, captain: Standing
) -> None:
    """Each wound worth two Wounds fells a three-Wound Maneater in two, the Captain last."""
    side = _maneaters()

    left = back_rank_multiplied(side.standing(4), wounds, Distribution.pure(2), side.removal)

    assert left == Distribution.pure(
        Standings((("maneater", maneaters), ("maneater-captain", captain)))
    )


def test_a_side_whose_parts_carry_different_rules_is_refused() -> None:
    """Rules attach to the whole side, so a rule only one part carries cannot be placed."""
    side = _maneaters()
    maneater, captain = side.parts
    extra = (RuleRef(rule="stubborn"), Source(Carrier.MODEL))
    mixed = replace(side, parts=(maneater, replace(captain, carried=(extra,))))

    with pytest.raises(ValueError, match="maneater-captain carries rules maneater does not"):
        list(mixed.sources())


@pytest.mark.parametrize(
    ("models", "frontage", "bonus"),
    [
        pytest.param(20, 5, 2, id="four-ranks-claim-the-cap-of-two"),
        pytest.param(15, 5, 2, id="three-ranks-claim-two"),
        pytest.param(14, 5, 1, id="a-rear-rank-of-four-does-not-count"),
        pytest.param(9, 5, 0, id="one-full-rank-claims-none"),
        pytest.param(11, 6, 1, id="a-rear-rank-of-five-counts"),
        pytest.param(20, 4, 0, id="four-wide-is-too-narrow-to-count"),
    ],
)
def test_the_rank_bonus_counts_the_ranks_behind_the_first(
    models: int, frontage: int, bonus: int
) -> None:
    """Elven Spearmen claim each rank behind the first holding five models, at most two."""
    contingent = Contingent.field(REPO.units["elven-spearmen"], 20, data=REPO, frontage=frontage)
    side = Fielding.of(contingent, combat=True)

    assert side.rank_bonus(side.standing(models)) == bonus


def test_a_side_counts_its_unit_strength_and_the_wounds_it_has_left() -> None:
    """Four Wounds on three Maneaters and a Captain fell one Maneater and hurt the next.

    Three Monstrous Infantry models stand at Unit Strength 3 each, with 9 Wounds
    less the 1 the hurt Maneater lost.
    """
    side = _maneaters()

    left = back_rank(side.standing(4), 4, side.removal)

    assert (side.unit_strength(left), side.wounds_left(left)) == (9, 8)
