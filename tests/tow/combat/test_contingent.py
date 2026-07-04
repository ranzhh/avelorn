"""The fielded unit: Contingent.deploy and the Charge bonus."""

import pytest

from avelorn.tow.combat.contingent import Charge, ChargeArc, Contingent, Loadout
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

    contingent = Contingent.deploy(
        mustered, weapons=REPO.weapons, armoury=REPO.armoury, charge=charge
    )

    assert contingent.models == 18
    assert contingent.charge is charge
    # The chosen option's rule is what the engine reads, not the printed profile.
    assert "Shieldwall" in contingent.unit.special_rules
    assert "Shieldwall" not in spearmen_unit.special_rules


def test_deploy_without_options_matches_the_datasheet(spearmen_unit: Unit) -> None:
    """With no options, the fielded loadout equals the printed datasheet."""
    contingent = Contingent.deploy(
        Complement(unit=spearmen_unit, size=10), weapons=REPO.weapons, armoury=REPO.armoury
    )

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


def test_deploy_resolves_equipment_into_the_loadout(spearmen_unit: Unit) -> None:
    """Fielding resolves printed equipment names to weapon and armour entries.

    Spearmen carry Hand Weapon and Thrusting Spear (weapons) plus Light
    Armour and Shield (armour); the loadout partitions them resolved, in
    equipment order.
    """
    contingent = Contingent.deploy(
        Complement(unit=spearmen_unit, size=10), weapons=REPO.weapons, armoury=REPO.armoury
    )
    assert contingent.loadout == Loadout(
        weapons=(REPO.weapons["hand-weapon"], REPO.weapons["thrusting-spear"]),
        armour=(REPO.armoury["light-armour"], REPO.armoury["shield"]),
    )


def test_deploy_resolves_option_granted_equipment() -> None:
    """Equipment added by a chosen option reaches the resolved loadout."""
    archers = REPO.units["elven-archers"]
    mustered = Complement(unit=archers, size=10, options=["Light Armour"])
    contingent = Contingent.deploy(mustered, weapons=REPO.weapons, armoury=REPO.armoury)
    assert contingent.loadout is not None
    assert REPO.armoury["light-armour"] in contingent.loadout.armour


def test_deploy_rejects_unresolvable_equipment(spearmen_unit: Unit) -> None:
    """A typo'd equipment name fails the deploy, naming the miss.

    The data covers every unit-referenced item, so at this seam a miss is
    an error to the list-builder, not a per-volley note.
    """
    typo = spearmen_unit.model_copy(update={"equipment": ["Hand Weapon", "Shjeld"]})
    with pytest.raises(ValueError, match=r"matches no weapon or armour: \['Shjeld'\]"):
        Contingent.deploy(
            Complement(unit=typo, size=10), weapons=REPO.weapons, armoury=REPO.armoury
        )


def test_direct_construction_carries_no_loadout(spearmen_unit: Unit) -> None:
    """An arbitrary body on the table has no resolved loadout (yet)."""
    assert Contingent(spearmen_unit, 5).loadout is None
