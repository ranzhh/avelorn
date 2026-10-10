"""Every rule entry with effects has exactly one test, named for the rule."""

import importlib
import inspect
from pathlib import Path

from avelorn.tow.data import DATA_DIR
from avelorn.tow.schema.rule import Rule
from rules.scenario import REPO

FAMILIES = sorted(Path(__file__).parent.glob("test_*_rules.py"))


def test_every_rule_with_effects_has_one_test_named_for_it() -> None:
    """A rule gaining effects needs its test; a test outliving its rule's effects goes."""
    filed = {path.stem for path in (DATA_DIR / "tow/rules").glob("*.yaml")}
    with_effects = {slug for slug in filed if _effects(REPO.rules[slug])}
    tested = [
        name.removeprefix("test_").replace("_", "-")
        for family in FAMILIES
        for name, _ in inspect.getmembers(
            importlib.import_module(f"rules.{family.stem}"), inspect.isfunction
        )
        if name.startswith("test_")
    ]
    assert sorted(tested) == sorted(with_effects)


def _effects(rule: Rule) -> bool:
    return bool(rule.effects) or (rule.graph is not None and bool(rule.graph.effects))
