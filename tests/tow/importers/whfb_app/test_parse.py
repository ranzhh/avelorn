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
    return json.loads((FIXTURES / f"{slug}.json").read_text())


@pytest.mark.parametrize("slug", [p.stem for p in FIXTURES.glob("*.json")])
def test_fixture_parses_to_valid_unit(slug: str) -> None:
    result = parse_unit(load_fixture(slug))
    assert isinstance(result, ImportResult)
    assert result.unit.id == slug


def test_spearmen_match_hand_authored_yaml() -> None:
    """The importer reproduces the hand-authored reference unit."""
    imported = parse_unit(load_fixture("elven-spearmen")).unit
    path = DATA_DIR / "tow/armies/high-elf-realms/units/elven-spearmen.yaml"
    hand = Unit.model_validate(yaml.safe_load(path.read_text()))

    # Equipment naming differs in case only: the site's canonical rule
    # entries are title case ("Hand Weapon"), the hand-authored file uses
    # the book's sentence case ("Hand weapon"). Open data question.
    assert [e.lower() for e in imported.equipment] == [e.lower() for e in hand.equipment]
    assert imported.model_dump(exclude={"equipment"}) == hand.model_dump(exclude={"equipment"})


def test_archers_parse_cleanly() -> None:
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


def test_war_machine_compound_base_size_left_unset() -> None:
    result = parse_unit(load_fixture("eagle-claw-bolt-thrower"))
    unit = result.unit
    assert unit.troop_type is TroopType.WAR_MACHINES
    assert unit.unit_size == UnitSize(min=1, max=1)
    assert unit.base_size is None
    assert any("base size" in w for w in result.warnings)
    # "-" stats in the war machine profile become None
    machine = unit.profiles[0]
    assert machine.movement is None
    assert machine.toughness == 6


def test_reavers_options_and_warnings() -> None:
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

    swap = by_name["Replace Cavalry Spear with shortbows"]
    assert swap.kind is OptionKind.EQUIPMENT
    assert swap.points == 1
    assert swap.per_model is True

    # The rider/steed equipment structure and the either/or shortbow
    # choice exceed the schema; both must surface as warnings.
    assert any("equipment has text not covered" in w for w in result.warnings)
    assert any("either/or" in w for w in result.warnings)


def test_character_troop_type_is_unsupported() -> None:
    entry = load_fixture("elven-spearmen")
    entry["fields"]["troopType"][0]["fields"]["name"] = "Character"
    with pytest.raises(UnsupportedUnit):
        parse_unit(entry)


def test_unknown_troop_type_is_an_error() -> None:
    entry = load_fixture("elven-spearmen")
    entry["fields"]["troopType"][0]["fields"]["name"] = "Irregular Infantry"
    with pytest.raises(WhfbParseError):
        parse_unit(entry)


def test_unparseable_unit_size_is_an_error() -> None:
    entry = load_fixture("elven-spearmen")
    entry["fields"]["unitSize"] = "varies"
    with pytest.raises(WhfbParseError):
        parse_unit(entry)
