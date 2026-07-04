"""The army-list layer: Complement, a unit as mustered into a list."""

import pytest
from pydantic import ValidationError

from avelorn.tow.data import TOWRepository
from avelorn.tow.muster import Complement
from avelorn.tow.schema.unit import Unit

REPO = TOWRepository()


@pytest.fixture
def spearmen_unit() -> Unit:
    """The Elven Spearmen datasheet, whose options a Complement is built from.

    Returns:
        The validated unit model.
    """
    return REPO.units["elven-spearmen"]


def test_complement_points_sum_models_and_flat_options(spearmen_unit: Unit) -> None:
    """A complement's points are per-model cost plus flat per-unit options."""
    # 10 Spearmen at 9 pts each, plus a Standard Bearer (5) and Musician (5).
    mustered = Complement(unit=spearmen_unit, size=10, options=["Standard Bearer", "Musician"])
    assert mustered.points == 10 * 9 + 5 + 5


def test_complement_per_model_option_costs_once_per_model(spearmen_unit: Unit) -> None:
    """A per-model option is charged for every model, and folds its rules."""
    # Veteran: +1 pt/model, adds "Veteran", removes "Valour of Ages".
    mustered = Complement(unit=spearmen_unit, size=10, options=["Veteran"])
    assert mustered.points == 10 * 9 + 10 * 1
    assert "Veteran" in mustered.special_rules
    assert "Valour of Ages" not in mustered.special_rules


def test_complement_option_adds_rule(spearmen_unit: Unit) -> None:
    """An option's adds_rules appears in the effective special rules."""
    mustered = Complement(unit=spearmen_unit, size=10, options=["Shieldwall"])
    assert "Shieldwall" in mustered.special_rules
    # Untaken options leave the datasheet loadout untouched.
    assert Complement(unit=spearmen_unit, size=10).special_rules == spearmen_unit.special_rules


def test_complement_size_below_minimum_rejected(spearmen_unit: Unit) -> None:
    """A size under the datasheet's minimum fails validation."""
    with pytest.raises(ValidationError, match="below the unit's minimum"):
        Complement(unit=spearmen_unit, size=4)


def test_complement_unknown_option_rejected(spearmen_unit: Unit) -> None:
    """An option the datasheet does not offer fails validation."""
    with pytest.raises(ValidationError, match="not offered"):
        Complement(unit=spearmen_unit, size=10, options=["Warpstone Amulet"])


def test_complement_duplicate_option_rejected(spearmen_unit: Unit) -> None:
    """The same option chosen twice fails validation."""
    with pytest.raises(ValidationError, match="duplicates"):
        Complement(unit=spearmen_unit, size=10, options=["Musician", "Musician"])
