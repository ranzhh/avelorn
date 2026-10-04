"""Rule sources and attaching."""

from avelorn.core.graph import Carrier, RuleNode, Source
from avelorn.tow.attach import attach_rules
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.kernels import Standing
from avelorn.tow.programs import VOLLEY, Evaluated, load_program
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.stage import Side
from avelorn.tow.steps import Fielded

REPO = TOWRepository()
VOLLEY_PROGRAM = load_program(VOLLEY, REPO.rules)


def _deployed(slug: str) -> Contingent:
    return Contingent.deploy(slug, REPO.units[slug].unit_size.min, data=REPO)


def _attached(attacker: Fielded, target: Fielded) -> dict[str, RuleNode]:
    attachment = attach_rules(
        VOLLEY_PROGRAM.program,
        VOLLEY_PROGRAM.specs,
        {Side.ATTACKER: attacker, Side.TARGET: target},
        REPO.rules,
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


def _evaluated(target: Contingent) -> tuple[Evaluated, ...]:
    archers = _deployed("elven-archers")
    return VOLLEY_PROGRAM.evaluate(
        {
            "attacker/fielded": Fielded.of(archers, "Longbow"),
            "target/fielded": Fielded.of(target),
            "distance": 12,
            "who-can-shoot": True,
            "line-of-sight": True,
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


def test_volley_fire_holds_a_node_where_the_volley_has_no_step_for_it() -> None:
    nodes = _attached(_archers(), Fielded.of(_deployed("elven-spearmen")))

    assert nodes["attacker/elven-archers/volley-fire"].landings == ()


def test_enemy_fire_is_honoured_where_skirmishers_is_declined() -> None:
    lanes = _evaluated(_deployed("shadow-warriors"))

    def read(evaluated: Evaluated) -> tuple[object, object]:
        view = evaluated.lane.to_view()
        (fire,) = (
            rule
            for rule in view["rules"]
            if rule["id"] == "target/shadow-warriors/enemy-fire-skirmishers"
        )
        return view["lanes"], fire["landings"][0]["verdicts"]

    skirmishers = "volley/may/target/skirmishers"
    assert [read(evaluated) for evaluated in lanes] == [
        ([{"decision": skirmishers, "outcome": "True"}], [{"verdict": "held", "p": 1.0}]),
        ([{"decision": skirmishers, "outcome": "False"}], [{"verdict": "honoured", "p": 1.0}]),
    ]


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
