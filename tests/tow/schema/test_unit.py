"""Unit model tests against real data files under data/."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from avelorn.tow.data import DATA_DIR
from avelorn.tow.schema.unit import (
    Characteristic,
    Profile,
    Unit,
    UnitOption,
    UnitSize,
)

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


def test_unit_files_discovered() -> None:
    """The data/ glob finds unit files; guards the parametrized test below."""
    assert UNIT_FILES


@pytest.mark.parametrize("path", UNIT_FILES, ids=lambda p: p.stem)
def test_unit_file_parses(path: Path) -> None:
    """Every unit YAML under data/ validates and carries its filename as id.

    The id/stem match is what lets TOWRepository key the unit registry
    by filename — the same guarantee the weapon and armour tests pin.
    """
    unit = Unit.model_validate(yaml.safe_load(path.read_text()))
    assert unit.id == path.stem


def test_dash_stat_becomes_none() -> None:
    """A "-" characteristic in source material is coerced to None."""
    stats = {"M": 4, "WS": 3, "BS": "-", "S": 3, "T": 3, "W": 1, "I": 3, "A": 1, "Ld": 7}
    profile = Profile.model_validate({"name": "Crew", **stats})
    assert profile[Characteristic.BALLISTIC_SKILL] is None


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


def test_unit_size_max_below_min_rejected() -> None:
    """A unit size range with max below min fails validation."""
    with pytest.raises(ValidationError):
        UnitSize.model_validate({"min": 5, "max": 4})


@pytest.mark.parametrize(
    "option",
    [
        {"name": "Both shapes", "points": 5, "points_budget": 50},
        {"name": "No cost"},
        {"name": "Negative", "points": -5},
        {"name": "Per-model budget", "points_budget": 50, "per_model": True},
    ],
    ids=["both-costs", "no-cost", "negative-points", "per-model-budget"],
)
def test_invalid_option_cost_shapes_rejected(option: dict) -> None:
    """Options must have exactly one non-negative cost shape."""
    with pytest.raises(ValidationError):
        UnitOption.model_validate(option)


def test_profile_requires_every_characteristic() -> None:
    """A row missing a printed column is a data error."""
    stats = {"M": 4, "WS": 3, "S": 3, "T": 3, "W": 1, "I": 3, "A": 1, "Ld": 7}  # no BS
    with pytest.raises(ValidationError, match="missing characteristics.*BS"):
        Profile.model_validate({"name": "Crew", **stats})


def test_profile_rejects_unknown_abbreviation() -> None:
    """A key outside the characteristic vocabulary is a data error."""
    stats = {"M": 4, "WS": 3, "BS": 3, "S": 3, "T": 3, "W": 1, "I": 3, "A": 1, "Ld": 7}
    with pytest.raises(ValidationError):
        Profile.model_validate({"name": "Crew", "Sv": 5, **stats})
