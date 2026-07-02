"""Rule schema tests: data/ validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from avelorn.core.loading import load_yaml
from avelorn.tow.schema.rule import Rule, RuleEffect

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


def test_effect_rejects_unknown_stage() -> None:
    """A stage outside the registry is a data error, not a silent inert."""
    with pytest.raises(ValidationError, match="stage"):
        RuleEffect.model_validate(
            {"kind": "armour-piercing", "stage": "roll-to-wnd", "on_natural": 6, "amount": 1}
        )


def test_effect_rejects_unknown_kind() -> None:
    """A kind outside the closed vocabulary is a data error."""
    with pytest.raises(ValidationError, match="kind"):
        RuleEffect.model_validate(
            {"kind": "reroll", "stage": "roll-to-wound", "on_natural": 6, "amount": 1}
        )


def test_effect_requires_its_kind_fields() -> None:
    """A kind's required fields are enforced by the schema, not a validator."""
    with pytest.raises(ValidationError, match="amount"):
        RuleEffect.model_validate({"kind": "armour-piercing", "stage": "roll-to-wound"})
