"""Rule pages parse into the paragraphs the printed rule is set in."""

import json
from pathlib import Path

import pytest

from avelorn.tow.importers.whfb_app.rules import parse_special_rule

_CAPTURED = Path(__file__).parent / "fixtures" / "rules"


@pytest.mark.parametrize(
    ("slug", "ends", "starts"),
    [
        pytest.param(
            "fear",
            "the unit can charge as normal.",
            "If a unit is engaged with an enemy unit",
            id="list-items",
        ),
        pytest.param(
            "motley-crew",
            "accompanied by a brief explanation of the unit's composition.",
            "Different Weapons",
            id="headings",
        ),
    ],
)
def test_printed_blocks_stay_separate_paragraphs(slug: str, ends: str, starts: str) -> None:
    """A list item or a heading is its own paragraph, parsed without a warning."""
    entry = json.loads((_CAPTURED / f"{slug}.json").read_text())
    result = parse_special_rule(entry)
    paragraphs = result.rule.paragraphs
    assert any(
        before.endswith(ends) and after.startswith(starts)
        for before, after in zip(paragraphs, paragraphs[1:], strict=False)
    )
    assert result.warnings == []
