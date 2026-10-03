import json
from itertools import pairwise
from pathlib import Path

from avelorn.tow.importers.whfb_app.rules import RuleImport, parse_special_rule

_CAPTURED = Path(__file__).parent / "fixtures" / "rules"


def _import(slug: str) -> RuleImport:
    return parse_special_rule(json.loads((_CAPTURED / f"{slug}.json").read_text()))


def test_list_items_are_separate_paragraphs() -> None:
    result = _import("fear")
    assert any(
        before.endswith("the unit can charge as normal.")
        and after.startswith("If a unit is engaged with an enemy unit")
        for before, after in pairwise(result.rule.paragraphs)
    )
    assert result.warnings == []


def test_heading_is_a_paragraph_of_its_own() -> None:
    result = _import("motley-crew")
    assert "Different Weapons" in result.rule.paragraphs
    assert result.warnings == []


def test_ordered_list_is_flagged_for_review() -> None:
    result = _import("choose-and-fight-combat")
    assert len(result.warnings) == 1
    assert "'ordered-list'" in result.warnings[0]
