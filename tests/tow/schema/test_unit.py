"""Unit model tests against real data files under data/."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from avelorn.tow.schema.unit import Profile, TroopType, Unit

DATA_DIR = Path(__file__).parents[3] / "data"
UNIT_FILES = sorted(DATA_DIR.glob("tow/armies/*/units/*.yaml"))


def load_unit(army: str, slug: str) -> dict:
    path = DATA_DIR / f"tow/armies/{army}/units/{slug}.yaml"
    return yaml.safe_load(path.read_text())


@pytest.fixture
def elven_spearmen() -> dict:
    return load_unit("high-elf-realms", "elven-spearmen")


@pytest.mark.parametrize("path", UNIT_FILES, ids=lambda p: p.stem)
def test_unit_file_parses(path: Path) -> None:
    Unit.model_validate(yaml.safe_load(path.read_text()))


def test_elven_spearmen_parses(elven_spearmen: dict) -> None:
    unit = Unit.model_validate(elven_spearmen)
    assert unit.points == 9
    assert unit.unit_size.min == 5
    assert unit.unit_size.max is None
    assert unit.troop_type is TroopType.REGULAR_INFANTRY
    assert len(unit.profiles) == 2
    sentinel = unit.profiles[1]
    assert sentinel.attacks == 2
    assert sentinel.leadership == 8
    assert "Valour of Ages" in unit.special_rules


def test_elven_archers_parses() -> None:
    unit = Unit.model_validate(load_unit("high-elf-realms", "elven-archers"))
    assert unit.points == 10
    assert unit.troop_type is TroopType.REGULAR_INFANTRY
    sentinel = unit.profiles[1]
    assert sentinel.ballistic_skill == 5
    assert sentinel.attacks == 1
    assert "Detachment" in unit.special_rules
    light_armour = next(o for o in unit.options if o.name == "Light armour")
    assert light_armour.per_model is True
    magic_standard = next(o for o in unit.options if o.name == "Magic standard")
    assert magic_standard.points_budget == 25


def test_dash_stat_becomes_none() -> None:
    profile = Profile.model_validate(
        {"name": "Crew", "M": 4, "WS": 3, "BS": "-", "S": 3, "T": 3, "W": 1, "I": 3, "A": 1, "Ld": 7}
    )
    assert profile.ballistic_skill is None


def test_unknown_field_rejected(elven_spearmen: dict) -> None:
    bad = dict(elven_spearmen, armour_save=5)
    with pytest.raises(ValidationError):
        Unit.model_validate(bad)


def test_unknown_troop_type_rejected(elven_spearmen: dict) -> None:
    bad = dict(elven_spearmen, troop_type="Irregular Infantry")
    with pytest.raises(ValidationError):
        Unit.model_validate(bad)
