"""The fielded unit: Contingent.deploy and the Charge bonus."""

import pytest

from avelorn.tow.combat.contingent import Charge, ChargeArc, Contingent
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
