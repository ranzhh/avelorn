"""Parser tests against captured whfb.app payloads.

Fixtures are real `/_next/data/.../unit/<slug>.json` entries with
Contentful boilerplate pruned and linked rule bodies stripped (the
importer only reads rule names). Recapture with:

    python -m avelorn.tow.importers.whfb_app unit <slug> --dry-run
"""

import json
from pathlib import Path

import pytest
import yaml

from avelorn.tow.importers.whfb_app.parse import (
    ImportResult,
    OptionKind,
    UnsupportedUnit,
    WhfbParseError,
    parse_unit,
)
from avelorn.tow.schema.unit import TroopType, Unit, UnitSize

FIXTURES = Path(__file__).parent / "fixtures"
DATA_DIR = Path(__file__).parents[4] / "data"


def load_fixture(slug: str) -> dict:
    """Load a captured unit entry.

    Returns:
        The entry as a dict.
    """
    return json.loads((FIXTURES / f"{slug}.json").read_text())


@pytest.mark.parametrize("slug", [p.stem for p in FIXTURES.glob("*.json")])
def test_fixture_parses_to_valid_unit(slug: str) -> None:
    """Every captured payload maps onto a valid Unit."""
    result = parse_unit(load_fixture(slug))
    assert isinstance(result, ImportResult)
    assert result.unit.id == slug


@pytest.mark.parametrize("slug", ["elven-spearmen", "elven-archers"])
def test_reference_units_match_hand_authored_yaml(slug: str) -> None:
    """The importer reproduces the hand-authored reference units."""
    imported = parse_unit(load_fixture(slug)).unit
    path = DATA_DIR / f"tow/armies/high-elf-realms/units/{slug}.yaml"
    hand = Unit.model_validate(yaml.safe_load(path.read_text()))
    assert imported == hand


def test_archers_parse_cleanly() -> None:
    """A regular regiment imports with zero warnings."""
    result = parse_unit(load_fixture("elven-archers"))
    assert result.warnings == []
    unit = result.unit
    assert unit.points == 10
    assert unit.unit_size == UnitSize(min=5)
    assert unit.troop_type is TroopType.REGULAR_INFANTRY
    armour = next(o for o in unit.options if o.name == "Light Armour")
    assert armour.kind is OptionKind.EQUIPMENT
    assert armour.points == 1
    assert armour.per_model is True
    assert armour.adds_equipment == ["Light Armour"]


def test_war_machine_compound_base_size_left_unset() -> None:
    """A compound base size is left unset and warned about."""
    result = parse_unit(load_fixture("eagle-claw-bolt-thrower"))
    unit = result.unit
    assert unit.troop_type is TroopType.WAR_MACHINE
    assert unit.unit_size == UnitSize(min=1, max=1)
    assert unit.base_size is None
    assert any("base size" in w for w in result.warnings)
    # The unit's printed weapon is more specific than the linked rules page.
    assert "Bolt Throwers" in unit.equipment
    assert any("'Repeater bolt thrower'" in w for w in result.warnings)
    # "-" stats in the war machine profile become None
    machine = unit.profiles[0]
    assert machine.movement is None
    assert machine.toughness == 6


def test_reavers_options_and_warnings() -> None:
    """Cavalry options parse and schema gaps surface as warnings."""
    result = parse_unit(load_fixture("ellyrian-reavers"))
    unit = result.unit
    assert unit.troop_type is TroopType.LIGHT_CAVALRY
    by_name = {o.name: o for o in unit.options}

    scouts = by_name["Scouts"]
    assert scouts.kind is OptionKind.SPECIAL_RULE
    assert scouts.adds_rules == ["Scouts"]
    assert scouts.limit == "0-1 unit per 1000 points"

    items = by_name["Harbinger magic items"]
    assert items.points_budget == 25

    swap = by_name["Shortbows"]
    assert swap.kind is OptionKind.EQUIPMENT
    assert swap.points == 1
    assert swap.per_model is True
    assert swap.adds_equipment == ["Shortbows"]
    assert swap.removes_equipment == ["Cavalry Spear"]

    # The rider/steed equipment structure and the either/or shortbow
    # choice exceed the schema; both must surface as warnings.
    assert any("equipment has text not covered" in w for w in result.warnings)
    assert any("either/or" in w for w in result.warnings)


def test_character_troop_type_is_unsupported() -> None:
    """Characters are skipped, not mangled into units."""
    entry = load_fixture("elven-spearmen")
    entry["fields"]["troopType"][0]["fields"]["name"] = "Character"
    with pytest.raises(UnsupportedUnit):
        parse_unit(entry)


def test_unknown_troop_type_is_an_error() -> None:
    """A troop type outside the enum fails loudly."""
    entry = load_fixture("elven-spearmen")
    entry["fields"]["troopType"][0]["fields"]["name"] = "Irregular Infantry"
    with pytest.raises(WhfbParseError):
        parse_unit(entry)


def test_unparseable_unit_size_is_an_error() -> None:
    """A unit size matching no known pattern fails loudly."""
    entry = load_fixture("elven-spearmen")
    entry["fields"]["unitSize"] = "varies"
    with pytest.raises(WhfbParseError):
        parse_unit(entry)
