"""Rule schema tests: data/ validation."""

from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from avelorn.core.loading import load_yaml
from avelorn.tow.data import DATA_DIR
from avelorn.tow.schema.rule import Condition, Rule, RuleEffect

_EFFECT = TypeAdapter(RuleEffect)

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
        _EFFECT.validate_python(
            {"kind": "armour-piercing", "stage": "roll-to-wnd", "on_natural": 6, "amount": 1}
        )


def test_effect_rejects_unknown_kind() -> None:
    """A kind outside the closed vocabulary is a data error."""
    with pytest.raises(ValidationError, match="kind"):
        _EFFECT.validate_python(
            {"kind": "reroll", "stage": "roll-to-wound", "on_natural": 6, "amount": 1}
        )


def test_effect_requires_its_kind_fields() -> None:
    """A kind's required fields are enforced by the schema, not a validator."""
    with pytest.raises(ValidationError, match="amount"):
        _EFFECT.validate_python({"kind": "armour-piercing", "stage": "roll-to-wound"})


def test_to_hit_effect_parses_with_condition() -> None:
    """The to-hit kind carries a printed-sign amount and a condition."""
    effect = _EFFECT.validate_python(
        {"kind": "to-hit", "stage": "roll-to-hit", "amount": -1, "when": {"at_long_range": True}}
    )
    assert effect.amount == -1
    assert effect.when is not None and effect.when[Condition.AT_LONG_RANGE] is True


def test_condition_outside_the_vocabulary_rejected() -> None:
    """A condition name outside the closed enum is a data error."""
    with pytest.raises(ValidationError, match="when"):
        _EFFECT.validate_python(
            {"kind": "to-hit", "stage": "roll-to-hit", "amount": -1, "when": {"charging": True}}
        )


def test_condition_must_ask_something() -> None:
    """An empty condition is meaningless."""
    with pytest.raises(ValidationError, match="at least 1"):
        _EFFECT.validate_python(
            {"kind": "to-hit", "stage": "roll-to-hit", "amount": -1, "when": {}}
        )


def test_reroll_effect_parses_with_causes() -> None:
    """The re-roll kind carries its seam and the printed cause filter."""
    effect = _EFFECT.validate_python(
        {
            "kind": "re-roll",
            "stage": "make-panic-tests",
            "causes": ["heavy-casualties", "fled-through"],
        }
    )
    assert effect.stage == "make-panic-tests"
    assert len(effect.causes) == 2


def test_reroll_effect_rejects_unknown_cause() -> None:
    """A cause outside the printed taxonomy is a data error."""
    with pytest.raises(ValidationError, match="causes"):
        _EFFECT.validate_python(
            {"kind": "re-roll", "stage": "make-panic-tests", "causes": ["bad-day"]}
        )
