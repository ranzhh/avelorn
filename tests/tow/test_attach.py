"""Rule sources and attaching."""

import re
from collections.abc import Mapping
from dataclasses import replace
from fractions import Fraction

import pytest

from avelorn.core.distribution import Probability
from avelorn.core.graph import Carrier, RuleNode, Source, Verdict
from avelorn.tow.attach import AttachError, attach_rules
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.kernels import Standing
from avelorn.tow.programs import VOLLEY, Evaluated, load_program
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import Clause, Rule, RuleGraph
from avelorn.tow.schema.stage import Side
from avelorn.tow.steps import Fielded

REPO = TOWRepository()
VOLLEY_PROGRAM = load_program(VOLLEY, REPO.rules)


def _deployed(slug: str) -> Contingent:
    return Contingent.deploy(slug, REPO.units[slug].unit_size.min, data=REPO)


def _attached(
    attacker: Fielded, target: Fielded, rules: Mapping[str, Rule] = REPO.rules
) -> dict[str, RuleNode]:
    attachment = attach_rules(
        VOLLEY_PROGRAM.program,
        VOLLEY_PROGRAM.specs,
        {Side.ATTACKER: attacker, Side.TARGET: target},
        rules,
        VOLLEY_PROGRAM.states,
    )
    return {node.id: node for node in attachment.nodes}


def _landed(node: RuleNode) -> list[tuple[str, list[str]]]:
    paths = VOLLEY_PROGRAM.program.paths
    return [
        (paths[landing.at], [paths[trigger] for trigger in landing.triggers])
        for landing in node.landings
    ]


def _archers() -> Fielded:
    return Fielded.of(_deployed("elven-archers"), "Longbow")


def _evaluated(
    target: Contingent,
    distance: int = 12,
    shooter: tuple[str, str] = ("elven-archers", "Longbow"),
) -> tuple[Evaluated, ...]:
    unit, weapon = shooter
    archers = _deployed(unit)
    return VOLLEY_PROGRAM.evaluate(
        {
            "attacker/fielded": Fielded.of(archers, weapon),
            "target/fielded": Fielded.of(target),
            "distance": distance,
            "can-shoot": True,
            "line-of-sight": True,
            "attacker/moved": False,
            "attacker/standing": Standing(archers.models, 0),
            "target/standing": Standing(target.models, 0),
            "target/models-at-start-of-phase": target.models,
            "target/battle-strength": target.models,
        }
    )


def test_a_side_carries_the_rules_of_the_profile_it_shoots_with() -> None:
    maneaters = Contingent.deploy("maneaters", 2, ["Brace of Ogre Pistols"], data=REPO)
    fielded = Fielded.of(maneaters, "Brace of Ogre Pistols")
    ranged = Source(Carrier.WEAPON, "brace-of-ogre-pistols", "Ranged")

    assert [pair for pair in fielded.sources() if pair[1].carrier is Carrier.WEAPON] == [
        (RuleRef(rule="armour-bane", X=1), ranged),
        (RuleRef(rule="multiple-shots", X=2), ranged),
        (RuleRef(rule="quick-shot"), ranged),
    ]


def test_a_bow_and_the_grant_to_it_make_one_armour_bane() -> None:
    sisters = Fielded.of(_deployed("sisters-of-avelorn"), "Bow of Avelorn")
    nodes = _attached(sisters, Fielded.of(_deployed("elven-archers")))
    bane = nodes["attacker/sisters-of-avelorn/armour-bane"]
    bow = Source(Carrier.WEAPON, "bow-of-avelorn", "Bow of Avelorn")

    assert bane.name == "Armour Bane (2)"
    assert bane.sources == (
        bow,
        Source(bow.carrier, bow.item, bow.profile, "attacker/sisters-of-avelorn/arrows-of-isha"),
    )
    assert _landed(bane) == [("volley/attack/make-armour-saves", ["volley/attack/roll-to-wound"])]


def test_only_the_side_taking_the_panic_test_holds_valour_of_ages() -> None:
    nodes = _attached(_archers(), Fielded.of(_deployed("elven-spearmen")))

    assert [
        (node.id, _landed(node)) for node in nodes.values() if node.rule == "valour-of-ages"
    ] == [
        (
            "target/elven-spearmen/valour-of-ages",
            [("volley/make-panic-tests", ["volley/heavy-casualties"])],
        )
    ]


def test_the_abyssal_cloak_lands_on_the_shooter_roll_to_hit() -> None:
    nodes = _attached(_archers(), Fielded.of(_deployed("merwyrm")))

    assert _landed(nodes["target/merwyrm/abyssal-cloak"]) == [
        ("volley/attack/roll-to-hit", ["volley/check-range"])
    ]


def test_volley_fire_lands_on_who_can_shoot() -> None:
    nodes = _attached(_archers(), Fielded.of(_deployed("elven-spearmen")))

    assert _landed(nodes["attacker/elven-archers/volley-fire"]) == [("volley/who-can-shoot", [])]


def _verdicts(evaluated: Evaluated, node: str) -> Mapping[Verdict, Probability]:
    (landing,) = evaluated.lane.program.rules[node].landings
    return evaluated.lane.verdicts(node, landing.at).mass


def test_enemy_fire_applies_only_where_skirmishers_is_taken() -> None:
    lanes = _evaluated(_deployed("shadow-warriors"))

    assert [
        (
            list(evaluated.lane.choices.values()),
            _verdicts(evaluated, "target/shadow-warriors/enemy-fire-skirmishers"),
        )
        for evaluated in lanes
    ] == [([True], {Verdict.APPLIED: 1}), ([False], {Verdict.HONOURED: 1})]


@pytest.mark.parametrize(
    ("distance", "penalty", "cloak"),
    [
        pytest.param(30, Verdict.CANCELLED, Verdict.APPLIED, id="long-range"),
        pytest.param(15, Verdict.HONOURED, Verdict.HONOURED, id="short-range"),
    ],
)
def test_the_abyssal_cloak_replaces_the_long_range_penalty(
    distance: int, penalty: Verdict, cloak: Verdict
) -> None:
    (evaluated,) = _evaluated(_deployed("merwyrm"), distance)

    assert _verdicts(evaluated, "attacker/elven-archers/firing-at-long-range") == {penalty: 1}
    assert _verdicts(evaluated, "target/merwyrm/abyssal-cloak") == {cloak: 1}


def test_armour_bane_applies_to_the_shots_that_wound_on_a_natural_six() -> None:
    (evaluated,) = _evaluated(
        _deployed("elven-spearmen"), shooter=("sisters-of-avelorn", "Bow of Avelorn")
    )
    wounded_on_a_six = Fraction(5, 6) * Fraction(1, 6)

    assert _verdicts(evaluated, "attacker/sisters-of-avelorn/armour-bane") == {
        Verdict.APPLIED: wounded_on_a_six,
        Verdict.HONOURED: 1 - wounded_on_a_six,
    }


def test_mundane_arrows_meet_witness_to_destiny_alone() -> None:
    (evaluated,) = _evaluated(_deployed("phoenix-guard"))

    assert _verdicts(evaluated, "target/phoenix-guard/witness-to-destiny") == {Verdict.APPLIED: 1}
    assert _verdicts(evaluated, "target/phoenix-guard/blessings-of-asuryan") == {
        Verdict.HONOURED: 1
    }


def test_valour_of_ages_applies_where_heavy_casualties_force_a_panic_test() -> None:
    (evaluated,) = _evaluated(_deployed("elven-spearmen"))
    tested = evaluated.at("volley/heavy-casualties").read("tested").mass[True]

    assert _verdicts(evaluated, "target/elven-spearmen/valour-of-ages") == {
        Verdict.APPLIED: tested,
        Verdict.HONOURED: 1 - tested,
    }


def test_a_gate_reading_a_band_check_range_never_outputs_is_refused() -> None:
    printed = REPO.rules["firing-at-long-range"]
    assert printed.graph is not None
    (effect,) = printed.graph.effects
    assert effect.when is not None
    far = effect.model_copy(update={"when": effect.when.model_copy(update={"is_": "far"})})
    misread = printed.with_graph(RuleGraph(clauses=(Clause(effect=far),)))

    with pytest.raises(
        AttachError,
        match=re.escape(
            "firing-at-long-range reads 'far' from volley/check-range, "
            "which outputs ['long', 'out-of-range', 'short']"
        ),
    ):
        _attached(
            _archers(),
            Fielded.of(_deployed("elven-spearmen")),
            {**REPO.rules, "firing-at-long-range": misread},
        )


def test_a_rule_with_no_x_carried_twice_to_a_landing_that_runs_is_refused() -> None:
    archers = _archers()
    twice = replace(
        archers,
        carried=(*archers.carried, (RuleRef(rule="moving-and-shooting"), Source(Carrier.MODEL))),
    )

    with pytest.raises(
        AttachError, match="moving-and-shooting at attacker/elven-archers has 2 sources"
    ):
        _attached(twice, Fielded.of(_deployed("elven-spearmen")))


def test_each_fielding_evaluates_with_its_own_rule_nodes() -> None:
    (spearmen,) = _evaluated(_deployed("elven-spearmen"))
    (merwyrm,) = _evaluated(_deployed("merwyrm"))

    def targets(evaluated: Evaluated) -> list[str]:
        return [node for node in evaluated.lane.program.rules if node.startswith("target/")]

    assert targets(spearmen) == [
        "target/elven-spearmen/close-order",
        "target/elven-spearmen/regimental-unit",
        "target/elven-spearmen/valour-of-ages",
    ]
    assert targets(merwyrm) == [
        "target/merwyrm/abyssal-cloak",
        "target/merwyrm/close-order",
        "target/merwyrm/fear",
        "target/merwyrm/large-target",
        "target/merwyrm/terror",
    ]
    assert VOLLEY_PROGRAM.program.rules == {}
