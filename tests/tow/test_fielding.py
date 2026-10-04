"""Tests for fielded sides made of parts."""

from dataclasses import replace

import pytest

from avelorn.core.graph import Carrier, Source
from avelorn.tow.data import TOWRepository
from avelorn.tow.fielding import Fielding, Part
from avelorn.tow.kernels import Standing, Standings, back_rank
from avelorn.tow.schema.reference import RuleRef

REPO = TOWRepository()
MANEATERS = REPO.units["maneaters"]


def _maneaters() -> Fielding:
    maneater, captain = MANEATERS.profiles
    return Fielding(
        "maneaters", (Part("maneater", maneater, 3), Part("maneater-captain", captain, 1)), 4
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


def test_a_side_whose_parts_carry_different_rules_is_refused() -> None:
    """Rules attach to the whole side, so a rule only one part carries cannot be placed."""
    side = _maneaters()
    maneater, captain = side.parts
    extra = (RuleRef(rule="stubborn"), Source(Carrier.MODEL))
    mixed = replace(side, parts=(maneater, replace(captain, carried=(extra,))))

    with pytest.raises(ValueError, match="maneater-captain carries rules maneater does not"):
        list(mixed.sources())
