"""Unit model tests against real data files under data/."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from avelorn.tow.schema.unit import Profile, TroopType, Unit

DATA_DIR = Path(__file__).parents[3] / "data"


@pytest.fixture
def elven_spearmen() -> dict:
    path = DATA_DIR / "tow/armies/high-elf-realms/units/elven-spearmen.yaml"
    return yaml.safe_load(path.read_text())


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
