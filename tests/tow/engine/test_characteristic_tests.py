"""Characteristic and Leadership test probabilities: exact counts."""

from fractions import Fraction

import pytest

from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.characteristic_tests import pass_probability, unit_pass_probability
from avelorn.tow.schema.unit import Characteristic

REPO = TOWRepository()

Ld = Characteristic.LEADERSHIP


@pytest.mark.parametrize(
    ("leadership", "expected"),
    [
        # Hand-counted cumulative ways to roll <= n on 2D6.
        (7, Fraction(21, 36)),
        (8, Fraction(26, 36)),
        (9, Fraction(30, 36)),
        (10, Fraction(33, 36)),
    ],
)
def test_leadership_matches_hand_count(leadership: int, expected: Fraction) -> None:
    """Golden 2D6 cumulative counts for the common Leadership values."""
    assert pass_probability(Ld, leadership) == expected


def test_leadership_natural_bounds() -> None:
    """The double 1 always passes; the double 6 always fails."""
    assert pass_probability(Ld, 1) == Fraction(1, 36)
    assert pass_probability(Ld, 12) == Fraction(35, 36)
    assert pass_probability(Ld, 20) == Fraction(35, 36)


def test_other_characteristics_roll_one_d6() -> None:
    """A Toughness test passes on roll <= T, natural 6 failing, 1 passing."""
    assert pass_probability(Characteristic.TOUGHNESS, 3) == Fraction(3, 6)
    assert pass_probability(Characteristic.TOUGHNESS, 6) == Fraction(5, 6)
    assert pass_probability(Characteristic.STRENGTH, 1) == Fraction(1, 6)


def test_zero_or_dash_fails_automatically() -> None:
    """A characteristic of 0 or "-" automatically fails the test."""
    for characteristic in (Characteristic.TOUGHNESS, Ld):
        assert pass_probability(characteristic, 0) == Fraction(0)
        assert pass_probability(characteristic, None) == Fraction(0)


def test_unit_tests_against_its_highest_value() -> None:
    """A unit with mixed values uses the highest it contains (printed)."""
    spearmen = REPO.units["elven-spearmen"]
    assert spearmen.highest(Ld) == 8
    assert unit_pass_probability(spearmen, Ld) == Fraction(26, 36)
    stripped = spearmen.model_copy(deep=True)
    for profile in stripped.profiles:
        profile.characteristics[Ld] = None
    assert stripped.highest(Ld) is None
    assert unit_pass_probability(stripped, Ld) == Fraction(0)
