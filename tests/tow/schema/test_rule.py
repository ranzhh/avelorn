"""Rule schema tests: data/ validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from avelorn.core.loading import load_yaml
from avelorn.tow.data import rule_paths
from avelorn.tow.schema.effect import Effect
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import (
    AmountParameter,
    DiceQuantity,
    Parameter,
    PrintedParameter,
    Rule,
    SelectorParameter,
    SelectorValue,
)

RULE_FILES = rule_paths()


def _piercing(amount: object) -> Effect:
    return Effect.model_validate(
        {
            "add": {"armour-piercing": amount},
            "at": {"step": "make-armour-saves", "by": "the-enemy"},
        }
    )


def test_data_glob_finds_files() -> None:
    """The data/ glob finds rule files; guards the parametrized test below."""
    assert RULE_FILES


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda p: p.stem)
def test_rule_yaml_is_valid(path: Path) -> None:
    """Every rule YAML under data/ validates against the schema."""
    rule = load_yaml(path, Rule)
    assert rule.id == path.stem
    assert rule.paragraphs


def test_an_effect_reads_x_only_where_the_rule_declares_one() -> None:
    """An effect may use "X" only on a rule declaring its parameter."""
    with pytest.raises(ValidationError, match="reads an X the rule does not declare"):
        Rule(id="doctored", name="Doctored", paragraphs=["..."], effects=(_piercing("X"),))


@pytest.mark.parametrize(
    "parameter",
    [
        SelectorParameter(kind="selector", values={"all-enemies": SelectorValue(printed="All")}),
        PrintedParameter(kind="printed"),
    ],
    ids=lambda parameter: parameter.kind,
)
def test_only_an_amount_x_is_read_by_an_effect(parameter: Parameter) -> None:
    """A selector or printed X names something no operation's amount can be."""
    with pytest.raises(ValidationError, match="reads an X the rule does not declare"):
        Rule(
            id="doctored",
            name="Doctored (X)",
            parameter=parameter,
            paragraphs=["…"],
            effects=(_piercing("X"),),
        )


def test_a_name_printing_x_declares_its_parameter() -> None:
    """A template with no parameter would bind no X and display the bare template."""
    with pytest.raises(ValidationError, match="prints an X, but the rule declares no parameter"):
        Rule(id="regeneration", name="Regeneration (X+)", paragraphs=["…"])


def test_a_printed_x_reads_and_displays_as_the_bracket_prints_it() -> None:
    """A text-only stub keeps its X verbatim until its parameter is declared."""
    stub = Rule(
        id="regeneration",
        name="Regeneration (X+)",
        parameter=PrintedParameter(kind="printed"),
        paragraphs=["…"],
    )
    reference = stub.read("Regeneration (5+)")
    assert reference == RuleRef(rule="regeneration", X=5)
    assert stub.bound(reference.x).name == "Regeneration (5+)"


def test_a_bounded_x_is_read_all_the_same() -> None:
    """The "X" a printed bound wraps is a parameter reference all the same."""
    with pytest.raises(ValidationError, match="reads an X the rule does not declare"):
        Rule(
            id="ironfist",
            name="Ironfist",
            paragraphs=["…"],
            effects=(_piercing({"amount": "X", "maximum": 2}),),
        )


def test_a_dice_x_never_binds_into_an_amount() -> None:
    """A rule may take a number or a roll; only the number binds into an amount an effect adds."""
    attacks = {
        "add": {"A": "X"},
        "of": "this-model",
        "at": {"step": "how-many-attacks", "by": "this-model"},
    }
    rule = Rule(
        id="extra-attacks",
        name="Extra Attacks (+X)",
        parameter=AmountParameter(kind="amount", dice=True),
        paragraphs=["…"],
        effects=(Effect.model_validate(attacks),),
    )
    assert rule.bound(1).name == "Extra Attacks (+1)"
    with pytest.raises(ValueError, match="'D3' is a dice roll, which binds only into a count"):
        rule.bound("D3")


@pytest.mark.parametrize(
    ("rule", "x", "refusal"),
    [
        (
            Rule(
                id="armour-bane",
                name="Armour Bane (X)",
                parameter=AmountParameter(kind="amount"),
                paragraphs=["…"],
            ),
            None,
            "X missing; armour-bane expects an amount",
        ),
        (Rule(id="stubborn", name="Stubborn", paragraphs=["…"]), 1, "X 1 given"),
    ],
    ids=["x-missing", "x-extra"],
)
def test_a_name_displays_only_with_the_x_its_rule_declares(
    rule: Rule, x: int | None, refusal: str
) -> None:
    """Neither the bare template nor a stray bracket is ever shown as a rule's name."""
    with pytest.raises(ValueError, match=refusal):
        rule.display(x)


def test_a_declared_parameter_prints_in_the_name() -> None:
    """Display substitutes X into the name, so the name must print one."""
    with pytest.raises(ValidationError, match="prints no X"):
        Rule(id="fly", name="Fly", parameter=AmountParameter(kind="amount"), paragraphs=["…"])


@pytest.mark.parametrize(
    ("printed", "sides", "plus"),
    [("D6", 6, 0), ("D3", 3, 0), ("D3+1", 3, 1)],
)
def test_dice_quantity_parses_the_printed_forms(printed: str, sides: int, plus: int) -> None:
    """Every dice quantity the army book prints parses to its die and addend."""
    quantity = DiceQuantity.parse(printed)
    assert quantity is not None
    assert (quantity.sides, quantity.plus) == (sides, plus)


@pytest.mark.parametrize("printed", ["2D6", "D4", "3", "Skirmishers", "D6-1"])
def test_dice_quantity_rejects_other_text(printed: str) -> None:
    """Text outside the printed dice forms is no quantity at all."""
    assert DiceQuantity.parse(printed) is None
