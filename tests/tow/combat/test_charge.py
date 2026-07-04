"""The charge sequence: Stand & Shoot reaction, hand-checked from the charts."""

from pathlib import Path

import pytest

from avelorn.core.loading import load_yaml, load_yaml_dir
from avelorn.tow.combat.charge import stand_and_shoot
from avelorn.tow.combat.melee import Contingent
from avelorn.tow.combat.shooting import shoot_unit
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon

DATA_DIR = Path(__file__).parents[3] / "data"

ARMOURY = {a.name: a for a in load_yaml_dir(DATA_DIR / "tow/armour", Armour)}
RULES = {r.name: r for r in load_yaml_dir(DATA_DIR / "tow/rules", Rule)}


def load_unit(slug: str) -> Unit:
    """Load an Elven unit from the data/ tree.

    Returns:
        The parsed unit model.
    """
    return load_yaml(DATA_DIR / f"tow/armies/high-elf-realms/units/{slug}.yaml", Unit)


def load_weapon(slug: str) -> Weapon:
    """Load a weapon from the data/ tree.

    Returns:
        The parsed weapon model.
    """
    return load_yaml(DATA_DIR / f"tow/weapons/{slug}.yaml", Weapon)


def test_stand_and_shoot_applies_the_minus_one_to_hit() -> None:
    """Archers standing and shooting hit at -1: BS4 (3+) becomes 4+."""
    archers, spearmen = load_unit("elven-archers"), load_unit("elven-spearmen")
    plain = shoot_unit(archers, spearmen, 10, load_weapon("longbow"), armoury=ARMOURY, rules=RULES)
    reaction = stand_and_shoot(
        Contingent(archers, 10),
        Contingent(spearmen, 10),
        load_weapon("longbow"),
        armoury=ARMOURY,
        rules=RULES,
    )
    assert plain.hit_target == 3
    assert reaction.hit_target == 4  # -1 To Hit for Standing and Shooting


def test_stand_and_shoot_is_exempt_from_firing_at_long_range() -> None:
    """The reaction never carries a Firing at Long Range note: the rule is a no-op.

    A plain volley with no distance leaves the range band unknown, so the
    rule is reported unfactored; the reaction asserts the exemption, so it
    is honoured silently instead.
    """
    archers, spearmen = load_unit("elven-archers"), load_unit("elven-spearmen")
    plain = shoot_unit(archers, spearmen, 10, load_weapon("longbow"), armoury=ARMOURY, rules=RULES)
    reaction = stand_and_shoot(
        Contingent(archers, 10),
        Contingent(spearmen, 10),
        load_weapon("longbow"),
        armoury=ARMOURY,
        rules=RULES,
    )
    assert any("Firing at Long Range" in note for note in plain.notes)
    assert not any("Firing at Long Range" in note for note in reaction.notes)


def test_stand_and_shoot_caps_casualties_at_the_charging_unit_size() -> None:
    """A volley cannot fell more chargers than the charging unit contains."""
    archers, spearmen = load_unit("elven-archers"), load_unit("elven-spearmen")
    reaction = stand_and_shoot(
        Contingent(archers, 20),
        Contingent(spearmen, 5),
        load_weapon("longbow"),
        armoury=ARMOURY,
        rules=RULES,
    )
    assert reaction.target_models == 5
    assert len(reaction.casualties) == 6  # 0..5
    assert sum(reaction.casualties) == pytest.approx(1.0)


def test_force_short_range_honours_long_range_as_a_no_op() -> None:
    """shoot_unit's force_short_range treats the shot as within half range."""
    archers, spearmen = load_unit("elven-archers"), load_unit("elven-spearmen")
    forced = shoot_unit(
        archers,
        spearmen,
        10,
        load_weapon("longbow"),
        armoury=ARMOURY,
        rules=RULES,
        force_short_range=True,
    )
    assert not any("Firing at Long Range" in note for note in forced.notes)
