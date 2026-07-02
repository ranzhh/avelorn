"""Rule schema tests: data/ validation."""

from pathlib import Path

import pytest

from avelorn.core.loading import load_yaml
from avelorn.tow.schema.rule import Rule

DATA_DIR = Path(__file__).parents[3] / "data"
RULE_FILES = sorted(DATA_DIR.glob("tow/rules/*.yaml"))


def test_data_glob_finds_files() -> None:
    """The data/ glob finds rule files; guards the parametrized test below."""
    assert RULE_FILES


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda p: p.stem)
def test_rule_yaml_is_valid(path: Path) -> None:
    """Every rule YAML under data/ validates against the schema."""
    rule = load_yaml(path, Rule)
    assert rule.id == path.stem
    assert rule.paragraphs
