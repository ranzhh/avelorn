"""Rule schema tests: data/ validation."""

from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from avelorn.core.loading import load_yaml
from avelorn.tow.data import DATA_DIR
from avelorn.tow.schema.rule import NATURAL, Condition, ModifierEffect, Rule, RuleEffect

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


def test_when_parses_state_beside_event() -> None:
    """One flat when: state conditions and the natural event, side by side."""
    effect = _EFFECT.validate_python(
        {
            "when": {"moved": True, "natural": {"face": 6, "roll": "roll-to-wound"}},
            "then": {"to-hit": -1},
        }
    )
    assert isinstance(effect, ModifierEffect)
    assert effect.conditions == {Condition.MOVED: True}
    assert effect.natural is not None and effect.natural.face == 6
    assert effect.then == {"to-hit": -1}


def test_when_is_optional() -> None:
    """Without a when, the modifier applies to every attack."""
    effect = _EFFECT.validate_python({"then": {"armour-piercing": 1}})
    assert isinstance(effect, ModifierEffect)
    assert effect.conditions == {}
    assert effect.natural is None


def test_natural_rejects_an_unknown_roll() -> None:
    """A roll outside the registry is a data error, not a silent inert."""
    with pytest.raises(ValidationError, match="roll"):
        _EFFECT.validate_python(
            {
                "when": {"natural": {"face": 6, "roll": "roll-to-wnd"}},
                "then": {"armour-piercing": 1},
            }
        )


def test_natural_rejects_an_impossible_face() -> None:
    """A natural face outside the die is a data error."""
    with pytest.raises(ValidationError, match="face"):
        _EFFECT.validate_python(
            {
                "when": {"natural": {"face": 7, "roll": "roll-to-wound"}},
                "then": {"armour-piercing": 1},
            }
        )


def test_natural_rejects_a_rollless_stage() -> None:
    """A natural face can only be shown by an attack roll's die.

    Make Panic Tests is a registry stage, but it rolls 2d6 for the
    whole unit — no single natural face exists there, so naming it is a
    data error at load, not a quiet unfactored note at compile.
    """
    with pytest.raises(ValidationError, match="not an attack roll"):
        _EFFECT.validate_python(
            {
                "when": {"natural": {"face": 6, "roll": "make-panic-tests"}},
                "then": {"armour-piercing": 1},
            }
        )


def test_natural_requires_a_roll_fact() -> None:
    """The event key takes a die's face, not a true/false."""
    with pytest.raises(ValidationError, match="natural"):
        _EFFECT.validate_python({"when": {"natural": True}, "then": {"armour-piercing": 1}})


def test_condition_requires_a_boolean_fact() -> None:
    """A state condition takes true/false, not a die's face."""
    with pytest.raises(ValidationError, match="true or false"):
        _EFFECT.validate_python(
            {
                "when": {"moved": {"face": 6, "roll": "roll-to-wound"}},
                "then": {"to-hit": -1},
            }
        )


def test_the_event_key_stays_outside_the_condition_vocabulary() -> None:
    """The reserved "natural" key must never collide with a Condition.

    Drift guard: both live in the same when mapping, so a member named
    "natural" joining the enum would shadow the event key.
    """
    assert NATURAL not in {condition.value for condition in Condition}


def test_then_rejects_an_unknown_quantity() -> None:
    """A quantity outside the closed vocabulary is a data error."""
    with pytest.raises(ValidationError, match="then"):
        _EFFECT.validate_python({"then": {"to-wnd": -1}})


def test_then_is_required() -> None:
    """A modifier without a consequence is meaningless."""
    with pytest.raises(ValidationError, match="then"):
        _EFFECT.validate_python({"when": {"moved": True}})


def test_then_must_move_something() -> None:
    """An empty then is meaningless."""
    with pytest.raises(ValidationError, match="at least 1"):
        _EFFECT.validate_python({"then": {}})


def test_modifier_rejects_a_spelled_out_stage() -> None:
    """Where a change lands follows from its quantity; a stage is a data error.

    Pins the migration: earlier shapes carried a top-level ``stage``,
    which must now fail loudly rather than parse inert.
    """
    with pytest.raises(ValidationError, match="stage"):
        _EFFECT.validate_python({"stage": "roll-to-hit", "then": {"to-hit": -1}})


def test_condition_outside_the_vocabulary_rejected() -> None:
    """A condition name outside the closed enum is a data error."""
    with pytest.raises(ValidationError, match="when"):
        _EFFECT.validate_python({"when": {"charging": True}, "then": {"to-hit": -1}})


def test_condition_must_ask_something() -> None:
    """An empty when is meaningless."""
    with pytest.raises(ValidationError, match="at least 1"):
        _EFFECT.validate_python({"when": {}, "then": {"to-hit": -1}})


def test_parameter_reference_requires_a_placeholder_name() -> None:
    """An effect may use "X" only under a name that prints one.

    An unbindable placeholder is a data error at load, not a runtime
    surprise.
    """
    with pytest.raises(ValidationError, match="X parameter"):
        Rule(
            id="armour-bane",
            name="Armour Bane",
            paragraphs=["…"],
            effects=[ModifierEffect(then={"armour-piercing": "X"})],
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
