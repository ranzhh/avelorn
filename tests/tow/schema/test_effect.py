"""The graph's rule schema: addresses, operations, and the legacy form beside them."""

import pytest
from pydantic import ValidationError

from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.effect import Effect, Operation, conflicts
from avelorn.tow.schema.rule import Clause, ModifierEffect

REPO = TOWRepository()
LANDS = {"at": {"step": "make-armour-saves", "by": "the-enemy"}}


@pytest.mark.parametrize(
    ("written", "refused"),
    [
        ({"at": {"step": "roll-to-hitt", "by": "this-model"}, "add": {"to-hit": -1}}, "type=enum"),
        ({"at": {"step": "check-range", "by": "this-model", "in": "combat"}, "deny": True}, "in"),
        ({**LANDS, "add": {"armour-piercing": 1}, "set": {"armour-piercing": 1}}, "add, set"),
        ({**LANDS, "add": {"armour-piercing": 1}, "range": 1}, "range"),
        ({"at": {"step": "who-strikes-first", "by": "this-model"}, "set": {"I": 10}}, "of names"),
        ({**LANDS, "grants": "armour-bane"}, "to"),
        ({**LANDS, "when": {"step": "make-armour-saves", "by": "the-enemy"}, "deny": True}, "own"),
        (
            {
                **LANDS,
                "when": {"step": "check-range", "by": "this-model", "natural": 6},
                "deny": True,
            },
            "rolls no",
        ),
    ],
    ids=[
        "unprinted step",
        "sequence not printing the step",
        "two operations",
        "unknown key",
        "characteristic without its owner",
        "grant without its receiver",
        "trigger on its own landing",
        "natural face of a measurement",
    ],
)
def test_an_effect_that_does_not_say_one_thing_fails_to_load(
    written: dict[str, object], refused: str
) -> None:
    """An effect names a printed step, one operation and every owner, or it does not load."""
    with pytest.raises(ValidationError, match=refused):
        Effect.model_validate(written)


def test_a_legacy_block_without_an_operation_reads_the_graphs() -> None:
    """The legacy engine takes the graph's add when its block names no operation."""
    clause = Clause.read(
        {
            "when": {"step": "roll-to-wound", "by": "this-model", "natural": 6},
            **LANDS,
            "add": {"armour-piercing": 1},
            "legacy": {"when": {"natural": {"face": 6, "roll": "roll-to-wound"}}},
        }
    )
    assert isinstance(clause.legacy, ModifierEffect)
    assert clause.legacy.add == {"armour-piercing": 1}
    assert clause.legacy.natural is not None and clause.legacy.natural.face == 6


def test_a_legacy_block_with_an_operation_reads_its_own() -> None:
    """A block naming its own operation is the legacy effect entire."""
    clause = Clause.read(
        {**LANDS, "set": {"armour-piercing": 1}, "legacy": {"add": {"to-hit": 1}}}
    )
    assert isinstance(clause.legacy, ModifierEffect)
    assert clause.legacy.add == {"to-hit": 1}
    assert clause.legacy.set_ is None


def test_an_effect_without_a_legacy_block_is_the_graphs_alone() -> None:
    """Without a legacy block the legacy engine never sees the effect."""
    clause = Clause.read({**LANDS, "add": {"armour-piercing": 1}})
    assert clause.effect is not None
    assert clause.legacy is None


def _uncancelled(slug: str) -> tuple[Effect, ...]:
    graph = REPO.rules[slug].graph
    assert graph is not None
    return tuple(effect for effect in graph.effects if effect.operation is not Operation.CANCELS)


def test_two_rules_setting_one_value_conflict_unless_one_cancels() -> None:
    """Strike First and Strike Last both set Initiative; only their cancels reconcile them."""
    both = {slug: _uncancelled(slug) for slug in ("strike-first", "strike-last")}
    assert conflicts(both) == [
        "strike-first and strike-last both set I at who-strikes-first by this-model, "
        "and neither cancels"
    ]
    graph = REPO.rules["strike-first"].graph
    assert graph is not None
    assert conflicts({**both, "strike-first": graph.effects}) == []


def test_two_rules_forcing_different_options_conflict() -> None:
    """A second rule forcing another Break test result clashes with Stubborn."""
    graph = REPO.rules["stubborn"].graph
    assert graph is not None
    gives = tuple(
        effect.model_copy(update={"force": ("gives-ground",)}) for effect in graph.effects
    )
    (found,) = conflicts({"stubborn": graph.effects, "doctored": gives})
    assert found.startswith("doctored and stubborn force gives-ground against")
    assert "at break-test by this-model" in found
