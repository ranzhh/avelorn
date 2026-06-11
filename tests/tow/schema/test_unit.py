"""Unit model tests against real data files under data/."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from avelorn.tow.schema.unit import Profile, Unit

DATA_DIR = Path(__file__).parents[3] / "data"
UNIT_FILES = sorted(DATA_DIR.glob("tow/armies/*/units/*.yaml"))


def load_unit(army: str, slug: str) -> dict:
    """Load a unit YAML file from data/ as a plain dict.

    Returns:
        The parsed YAML content, unvalidated.
    """
    path = DATA_DIR / f"tow/armies/{army}/units/{slug}.yaml"
    return yaml.safe_load(path.read_text())


@pytest.fixture
def elven_spearmen() -> dict:
    """Elven Spearmen reference data, used to exercise schema rejections.

    Returns:
        The unit as a plain dict.
    """
    return load_unit("high-elf-realms", "elven-spearmen")


@pytest.mark.parametrize("path", UNIT_FILES, ids=lambda p: p.stem)
def test_unit_file_parses(path: Path) -> None:
    """Every unit YAML under data/ validates against the schema."""
    Unit.model_validate(yaml.safe_load(path.read_text()))


def test_dash_stat_becomes_none() -> None:
    """A "-" characteristic in source material is coerced to None."""
    stats = {"M": 4, "WS": 3, "BS": "-", "S": 3, "T": 3, "W": 1, "I": 3, "A": 1, "Ld": 7}
    profile = Profile.model_validate({"name": "Crew", **stats})
    assert profile.ballistic_skill is None


def test_unknown_field_rejected(elven_spearmen: dict) -> None:
    """Fields not in the schema fail validation instead of passing silently."""
    bad = dict(elven_spearmen, armour_save=5)
    with pytest.raises(ValidationError):
        Unit.model_validate(bad)


def test_unknown_troop_type_rejected(elven_spearmen: dict) -> None:
    """Troop types outside the closed enum fail validation."""
    bad = dict(elven_spearmen, troop_type="Irregular Infantry")
    with pytest.raises(ValidationError):
        Unit.model_validate(bad)
