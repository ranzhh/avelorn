"""The mustering layer: Complement, Contingent.deploy, and the Charge bonus."""

import pytest
from pydantic import ValidationError

from avelorn.tow.data import TOWRepository
from avelorn.tow.muster import Charge, ChargeArc, Complement, Contingent
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


def test_deploy_fields_complement_size_and_loadout(spearmen_unit: Unit) -> None:
    """Contingent.deploy carries the complement's size and chosen loadout."""
    mustered = Complement(unit=spearmen_unit, size=18, options=["Shieldwall"])
    charge = Charge(6, ChargeArc.FRONT)

    contingent = Contingent.deploy(mustered, charge)

    assert contingent.models == 18
    assert contingent.charge is charge
    # The chosen option's rule is what the engine reads, not the printed profile.
    assert "Shieldwall" in contingent.unit.special_rules
    assert "Shieldwall" not in spearmen_unit.special_rules


def test_deploy_without_options_matches_the_datasheet(spearmen_unit: Unit) -> None:
    """With no options, the fielded loadout equals the printed datasheet."""
    contingent = Contingent.deploy(Complement(unit=spearmen_unit, size=10))

    assert contingent.unit.equipment == spearmen_unit.equipment
    assert contingent.unit.special_rules == spearmen_unit.special_rules


@pytest.mark.parametrize(
    ("inches", "arc", "expected"),
    [
        (0, ChargeArc.FRONT, 0),
        (2, ChargeArc.FRONT, 2),  # +1 per full inch
        (5, ChargeArc.FRONT, 3),  # capped at +3 into the front arc
        (5, ChargeArc.FLANK, 4),  # +4 into the flank
        (5, ChargeArc.REAR, 4),  # +4 into the rear
        (-1, ChargeArc.FRONT, 0),  # never negative
    ],
)
def test_charge_initiative_bonus_caps(inches: int, arc: ChargeArc, expected: int) -> None:
    """+1 Initiative per full inch, capped by arc (+3 front, +4 flank/rear)."""
    assert Charge(inches, arc).initiative_bonus() == expected
