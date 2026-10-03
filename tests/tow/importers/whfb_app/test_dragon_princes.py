"""The Dragon Princes page, captured and trimmed to the fields the importer reads."""

import json
from pathlib import Path

from avelorn.tow.data import DATA_DIR, TOWRepository
from avelorn.tow.importers.whfb_app.canon import canonical_unit
from avelorn.tow.importers.whfb_app.parse import parse_unit
from avelorn.tow.importers.whfb_app.references import RuleReferences
from avelorn.tow.importers.whfb_app.richtext import Node, list_items
from avelorn.tow.importers.whfb_app.yamlout import unit_to_yaml

REPO = TOWRepository()
_PAGE = Path(__file__).parent / "fixtures" / "units" / "dragon-princes.json"
_DATASHEET = DATA_DIR / "tow" / "armies" / "high-elf-realms" / "units" / "dragon-princes.yaml"


def _entry() -> Node:
    return json.loads(_PAGE.read_text())


def _references() -> RuleReferences:
    return RuleReferences(REPO.rules.values())


def test_the_page_imports_as_the_datasheet() -> None:
    """Importing the page writes the committed datasheet."""
    equipment = {item.name for item in (*REPO.weapons.values(), *REPO.armoury.values())}
    unit, _ = canonical_unit(parse_unit(_entry(), _references()).unit, equipment=equipment)
    source = "https://tow.whfb.app/unit/dragon-princes"
    assert unit_to_yaml(unit, source_url=source) == _DATASHEET.read_text()


def test_a_weapon_only_the_mount_carries_stays_off_the_unit() -> None:
    """The steed's own weapon arms the steed; its barding stays the unit's."""
    entry = _entry()
    *_, mount = list_items(entry["fields"]["equipment"])

    def rename(node: Node) -> None:
        target = node.get("data", {}).get("target", {})
        if target.get("fields", {}).get("name") == "Hand Weapon":
            target["fields"]["name"] = "Claws"
        for child in node.get("content", []):
            rename(child)

    rename(mount)
    result = parse_unit(entry, _references())
    assert result.unit.mount is not None
    assert result.unit.mount.equipment == ["Claws"]
    assert "Claws" not in result.unit.equipment
    assert "Barding" in result.unit.equipment
