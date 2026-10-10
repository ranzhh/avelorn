"""Unit model tests against real data files under data/."""

from collections.abc import Callable
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


def test_highest_reads_the_unit_s_highest_value(elven_spearmen: dict) -> None:
    """A unit tests against its highest value; with none printed there is none."""
    unit = Unit.model_validate(elven_spearmen)
    unit.profiles[1].characteristics[Characteristic.LEADERSHIP] = 9
    assert unit.highest(Characteristic.LEADERSHIP) == 9
    for profile in unit.profiles:
        profile.characteristics[Characteristic.LEADERSHIP] = None
    assert unit.highest(Characteristic.LEADERSHIP) is None


def test_dash_stat_becomes_none() -> None:
    """A "-" characteristic in source material is coerced to None."""
    stats = {"M": 4, "WS": 3, "BS": "-", "S": 3, "T": 3, "W": 1, "I": 3, "A": 1, "Ld": 7}
    profile = Profile.model_validate({"name": "Crew", "role": "rank-and-file", **stats})
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


def test_option_attaches_to_a_printed_model(elven_spearmen: dict) -> None:
    """An option may name a model the unit prints a profile for."""
    option = {
        "name": "Shield",
        "kind": "equipment",
        "scope": "model",
        "applies_to": "Sentinel",
        "points": 2,
    }
    unit = Unit.model_validate(dict(elven_spearmen, options=[*elven_spearmen["options"], option]))
    assert unit.options[-1].applies_to == "Sentinel"


def test_option_attached_to_an_absent_model_rejected(elven_spearmen: dict) -> None:
    """A model with no profile row cannot carry an option."""
    option = {
        "name": "Shield",
        "kind": "equipment",
        "scope": "model",
        "applies_to": "Sea Master",
        "points": 2,
    }
    with pytest.raises(ValidationError, match="no profile"):
        Unit.model_validate(dict(elven_spearmen, options=[*elven_spearmen["options"], option]))


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
        Profile.model_validate({"name": "Crew", "role": "rank-and-file", **stats})


def test_profile_rejects_unknown_abbreviation() -> None:
    """A key outside the characteristic vocabulary is a data error."""
    stats = {"M": 4, "WS": 3, "BS": 3, "S": 3, "T": 3, "W": 1, "I": 3, "A": 1, "Ld": 7}
    with pytest.raises(ValidationError, match="Sv"):
        Profile.model_validate({"name": "Crew", "role": "rank-and-file", "Sv": 5, **stats})


_RIDER = {
    "name": "Rider",
    "role": "rank-and-file",
    "M": "-",
    "WS": 4,
    "BS": 4,
    "S": 3,
    "T": 3,
    "W": 1,
    "I": 5,
    "A": 1,
    "Ld": 8,
}
_STEED = {
    "name": "Steed",
    "role": "mount",
    "M": 8,
    "WS": 3,
    "BS": "-",
    "S": 3,
    "T": "-",
    "W": "-",
    "I": 4,
    "A": 1,
    "Ld": "-",
}


def _ridden() -> Unit:
    return Unit.model_validate(
        {
            "id": "riders",
            "name": "Riders",
            "points": 20,
            "unit_size": {"min": 5},
            "troop_type": "Heavy Cavalry",
            "profiles": [_RIDER, _STEED],
        }
    )


def test_a_row_must_state_its_role() -> None:
    """A row without a role is refused: nothing guesses which part of the unit it is."""
    unstated = {key: value for key, value in _RIDER.items() if key != "role"}
    with pytest.raises(ValidationError, match="role"):
        Profile.model_validate(unstated)


def _without_the_champion_option(unit: dict) -> None:
    unit["options"] = [o for o in unit["options"] if o["kind"] != "champion"]


def _champion_naming_the_rank_and_file(unit: dict) -> None:
    unit["options"][0]["profile"] = "Elven Spearman"


def _champion_naming_no_row(unit: dict) -> None:
    del unit["options"][0]["profile"]


def _unit_scope_for_a_named_model(unit: dict) -> None:
    unit["options"][3].update(applies_to="Sentinel", scope="unit")


def _two_options_printing_one_name(unit: dict) -> None:
    unit["options"].append({**unit["options"][2], "kind": "other"})


def _equipment_on_the_rank_and_file(unit: dict) -> None:
    unit["profiles"][0]["equipment"] = ["Hand Weapon"]


def _no_rank_and_file_row(unit: dict) -> None:
    unit["profiles"] = [row for row in unit["profiles"] if row["role"] != "rank-and-file"]


def _two_rank_and_file_rows(unit: dict) -> None:
    unit["profiles"].append({**_RIDER, "name": "Second Rider"})


def _two_mount_rows(unit: dict) -> None:
    unit["profiles"].extend([_STEED, {**_STEED, "name": "Second Steed"}])


@pytest.mark.parametrize(
    ("edit", "refusal"),
    [
        (_without_the_champion_option, "no option names the champion rows: \\['Sentinel'\\]"),
        (_champion_naming_the_rank_and_file, "name no champion row"),
        (_champion_naming_no_row, "names a profile row"),
        (_unit_scope_for_a_named_model, "must have model scope"),
        (_two_options_printing_one_name, "options share an id: \\['musician'\\]"),
        (_equipment_on_the_rank_and_file, "only a mount row lists equipment"),
        (_no_rank_and_file_row, "needs one rank-and-file row, has 0"),
        (_two_rank_and_file_rows, "needs one rank-and-file row, has 2"),
        (_two_mount_rows, "may have one mount row, has 2"),
    ],
    ids=[
        "champion-row-unnamed",
        "champion-names-rank-and-file",
        "champion-names-no-row",
        "named-model-unit-scope",
        "two-options-one-id",
        "rank-and-file-lists-equipment",
        "no-rank-and-file",
        "two-rank-and-file",
        "two-mounts",
    ],
)
def test_parts_are_checked_at_load(
    elven_spearmen: dict, edit: Callable[[dict], None], refusal: str
) -> None:
    """Rows and options must agree on which row is the champion and who takes what."""
    edit(elven_spearmen)
    with pytest.raises(ValidationError, match=refusal):
        Unit.model_validate(elven_spearmen)


def test_main_is_the_rank_and_file_row() -> None:
    """`Unit.main` is the rider of a cavalry datasheet, whose T and W the model uses."""
    unit = _ridden()
    assert unit.main.name == "Rider"
    assert unit.main[Characteristic.TOUGHNESS] == 3


def test_the_mount_row_is_the_one_the_unit_rides() -> None:
    """`Unit.mount` finds the row every model of the unit sits on."""
    unit = _ridden()
    assert unit.mount is not None
    assert unit.mount.name == "Steed"
    assert unit.mount[Characteristic.MOVEMENT] == 8


def test_a_unit_on_foot_rides_nothing() -> None:
    """A single-row datasheet has a main and no mount."""
    unit = Unit.model_validate(
        {
            "id": "footmen",
            "name": "Footmen",
            "points": 5,
            "unit_size": {"min": 5},
            "troop_type": "Regular Infantry",
            "profiles": [{**_RIDER, "name": "Footman", "M": 5}],
        }
    )
    assert unit.main.name == "Footman"
    assert unit.mount is None
