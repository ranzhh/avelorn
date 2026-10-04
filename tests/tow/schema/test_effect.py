"""The graph's rule schema: addresses, operations, and the legacy form beside them."""

import pytest
from pydantic import ValidationError

from avelorn.core.graph import Side as Role
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.effect import Address, Effect, Operation, conflicts
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
        (
            {"at": {"step": "roll-to-hit", "by": "this-model", "in": "break-test"}, "deny": True},
            "runs no",
        ),
        ({"at": {"step": "check-range", "by": "this-model"}, "deny": True}, "takes away a roll"),
        ({"at": {"step": "who-can-shoot", "by": "this-model"}, "reroll": "failed"}, "rolls none"),
        ({"at": {"step": "check-range", "by": "this-model"}, "hits": 1}, "no slot"),
        ({"at": {"step": "check-range", "by": "this-model"}, "fill": True}, "no slot"),
        (
            {"at": {"step": "check-range", "by": "this-model"}, "force": ["long"]},
            "or a decision",
        ),
        (
            {"at": {"step": "check-range", "by": "this-model"}, "substitute": {"long": "short"}},
            "or a decision",
        ),
        ({"at": {"step": "impact-hits", "by": "this-model"}, "hits": 0}, "at least one"),
        ({"at": {"step": "check-range", "by": "this-model"}, "multiply": 1}, "less than 2"),
        (
            {"at": {"step": "impact-hits", "by": "this-model", "in": "impact-hits"}, "hits": 1},
            "runs no",
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
        "block not running the step",
        "deny at a measurement",
        "reroll where no die is rolled",
        "hits outside a slot",
        "fill outside a slot",
        "force at a measurement",
        "substitute at a measurement",
        "no hits",
        "multiplying by one",
        "step inside its own block",
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
    """Strike First and Strike Last both set Initiative; either one's cancel reconciles them."""
    both = {slug: _uncancelled(slug) for slug in ("strike-first", "strike-last")}
    assert conflicts(both) == [
        "strike-first and strike-last both set I at who-strikes-first by this-model, "
        "and neither cancels"
    ]
    for slug in both:
        graph = REPO.rules[slug].graph
        assert graph is not None
        assert conflicts({**both, slug: graph.effects}) == []


def test_a_cancel_reaches_only_its_own_address() -> None:
    """Strike First's cancel, moved to where the enemy acts, no longer reaches Strike Last."""
    graph = REPO.rules["strike-first"].graph
    assert graph is not None
    moved = tuple(
        effect.model_copy(update={"at": effect.at.mirrored()})
        if effect.cancels is not None and effect.at is not None
        else effect
        for effect in graph.effects
    )
    assert conflicts({"strike-first": moved, "strike-last": _uncancelled("strike-last")}) != []


def test_a_rule_on_the_enemy_conflicts_where_both_land() -> None:
    """Setting the enemy's Initiative clashes with the enemy's own Strike First."""
    chill = _landing("strike-last", {"by": "the-enemy"})
    chill = tuple(effect.model_copy(update={"of": Role.THE_ENEMY}) for effect in chill)
    (found,) = conflicts({"strike-first": _uncancelled("strike-first"), "strike-last": chill})
    assert found.startswith("strike-first and the enemy's strike-last both set I")


def test_rules_changing_different_models_never_conflict() -> None:
    """Initiative set for the bearer and for the enemy at one step are two values."""
    chill = tuple(
        effect.model_copy(update={"of": Role.THE_ENEMY}) for effect in _uncancelled("strike-last")
    )
    assert conflicts({"strike-first": _uncancelled("strike-first"), "strike-last": chill}) == []


def test_rules_landing_for_different_roles_never_conflict() -> None:
    """The bearer's Initiative set where it acts and where the enemy acts are two landings."""
    elsewhere = _landing("strike-last", {"by": "the-enemy"})
    assert (
        conflicts({"strike-first": _uncancelled("strike-first"), "strike-last": elsewhere}) == []
    )


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


def _landing(slug: str, at: dict[str, str]) -> tuple[Effect, ...]:
    (effect, *_) = _uncancelled(slug)
    assert effect.at is not None
    address = Address.model_validate({**effect.at.model_dump(by_alias=True), **at})
    return (effect.model_copy(update={"at": address}),)


def test_rules_in_different_blocks_never_conflict() -> None:
    """Automatic hits from Impact Hits and from Stomp Attacks are never the same wound roll."""
    impact = _landing("strike-first", {"step": "roll-to-wound", "in": "impact-hits"})
    stomp = _landing("strike-last", {"step": "roll-to-wound", "in": "stomp-attacks"})
    assert conflicts({"strike-first": impact, "strike-last": stomp}) == []
    stomp = _landing("strike-last", {"step": "roll-to-wound", "in": "impact-hits"})
    assert conflicts({"strike-first": impact, "strike-last": stomp}) != []
