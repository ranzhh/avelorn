"""Mount rows read from a captured datasheet's equipment field."""

import json
from pathlib import Path

from avelorn.tow.data import TOWRepository
from avelorn.tow.importers.whfb_app.parse import _with_mount_weapons

_CAPTURED = Path(__file__).parent / "fixtures" / "units"


def test_mount_row_lists_the_weapons_its_line_prints() -> None:
    """The Barded Elven Steed's hooves count as a hand weapon; its barding stays the unit's."""
    equipment = json.loads((_CAPTURED / "dragon-princes-equipment.json").read_text())
    rows = [
        row.model_copy(update={"equipment": []})
        for row in TOWRepository().units["dragon-princes"].profiles
    ]
    warnings: list[str] = []
    *_, steed = _with_mount_weapons("dragon-princes", rows, equipment, warnings)
    assert steed.equipment == ["Hand Weapon"]
    assert warnings == []
