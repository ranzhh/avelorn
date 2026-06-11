"""YAML output round-trips through the schema and matches the hand style."""

import json
from pathlib import Path

import pytest
import yaml

from avelorn.tow.importers.whfb_app.parse import parse_unit
from avelorn.tow.importers.whfb_app.yamlout import unit_to_yaml
from avelorn.tow.schema.unit import Unit

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("slug", [p.stem for p in FIXTURES.glob("*.json")])
def test_yaml_round_trips(slug: str) -> None:
    """Generated YAML reloads into an equal Unit."""
    unit = parse_unit(json.loads((FIXTURES / f"{slug}.json").read_text())).unit
    reloaded = Unit.model_validate(yaml.safe_load(unit_to_yaml(unit)))
    assert reloaded == unit


def test_output_matches_hand_authored_style() -> None:
    """Generated YAML follows the hand-authored formatting."""
    unit = parse_unit(json.loads((FIXTURES / "elven-spearmen.json").read_text())).unit
    text = unit_to_yaml(unit, source_url="https://tow.whfb.app/unit/elven-spearmen")
    lines = text.splitlines()
    assert lines[0] == "# Source: https://tow.whfb.app/unit/elven-spearmen"
    assert (
        "  - { name: Elven Spearman, M: 5, WS: 4, BS: 4, S: 3, T: 3, W: 1, I: 4, A: 1, Ld: 8 }"
        in lines
    )
    assert "    adds_rules: [Shieldwall]" in lines
    # block sequences are indented under their key
    assert "  - Close Order" in lines
