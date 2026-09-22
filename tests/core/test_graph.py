import re
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from avelorn.core.distribution import Distribution, Monoid
from avelorn.core.graph import (
    Bearer,
    Consequence,
    Decision,
    GraphError,
    Landing,
    Lanes,
    Measurement,
    Modifier,
    Program,
    Projection,
    Repeat,
    Roll,
    RuleNode,
    Scalar,
    Sequence,
    Side,
    Slot,
    Trace,
    Verdict,
)

_SIXTH = Fraction(1, 6)
_HALF = Fraction(1, 2)
_SIDES = {Side.THIS_MODEL: "the archers", Side.THE_ENEMY: "the spearmen"}


def _d6() -> Distribution[int]:
    return Distribution({face: _SIXTH for face in range(1, 7)})


def _coin() -> Distribution[int]:
    return Distribution({0: _HALF, 1: _HALF})


def _three() -> Distribution[int]:
    return Distribution.pure(3)


def _one() -> Distribution[int]:
    return Distribution.pure(1)


def test_a_roll_edge_carries_its_own_distribution() -> None:
    flip = Roll[int](name="flip", side=Side.THIS_MODEL, kernel=_coin, target=Scalar("target", 1))
    program = Program.build("coin", _SIDES, (flip,))

    (lane,) = program.evaluate()

    assert lane.read(flip, flip.output("face", Monoid(0))).mass == {0: _HALF, 1: _HALF}


def test_a_path_is_the_step_place_in_the_block_tree() -> None:
    shots = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_three)
    hit = Roll[int](name="roll-to-hit", side=Side.THIS_MODEL, kernel=_d6, target=Scalar("t", 4))
    attack = Repeat(name="attack", times=shots, items=(hit,))
    program = Program.build("volley", _SIDES, (shots, attack))

    assert program.paths[shots] == "volley/shots"
    assert program.paths[attack] == "volley/attack"
    assert program.paths[hit] == "volley/attack/roll-to-hit"
    assert program.steps == [shots, hit]
    assert program.blocks == [attack]


_certain_shots = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_three)
_certain_die = Roll[int](name="roll", side=Side.THIS_MODEL, kernel=_d6, target=Scalar("t", 6))
_certain = Program.build(
    "certain",
    _SIDES,
    (_certain_shots, Repeat(name="attack", times=_certain_shots, items=(_certain_die,))),
)


def _certain_six(world: Trace) -> int:
    return 1 if world.of(_certain_die) == 6 else 0


def test_a_reading_stacks_a_certain_count() -> None:
    (lane,) = _certain.evaluate()
    stacked = lane.read(_certain_die, Projection("sixes", _certain_six, Monoid(0)))

    assert stacked.mass == {
        0: Fraction(125, 216),
        1: Fraction(75, 216),
        2: Fraction(15, 216),
        3: Fraction(1, 216),
    }


def _two_or_three() -> Distribution[int]:
    return Distribution({2: _HALF, 3: _HALF})


_open_shots = Roll[int](
    name="shots", side=Side.THIS_MODEL, kernel=_two_or_three, target=Scalar("t", 1)
)
_open_die = Roll[int](name="roll", side=Side.THIS_MODEL, kernel=_d6, target=Scalar("t", 6))
_open = Program.build(
    "open",
    _SIDES,
    (_open_shots, Repeat(name="attack", times=_open_shots, items=(_open_die,))),
)


def _open_six(world: Trace) -> int:
    return 1 if world.of(_open_die) == 6 else 0


def test_a_reading_stacks_an_uncertain_count() -> None:
    (lane,) = _open.evaluate()
    stacked = lane.read(_open_die, Projection("sixes", _open_six, Monoid(0)))

    assert stacked.mass == {
        0: Fraction(275, 432),
        1: Fraction(135, 432),
        2: Fraction(21, 432),
        3: Fraction(1, 432),
    }


def _none_or_two() -> Distribution[int]:
    return Distribution({0: _HALF, 2: _HALF})


_spent_shots = Roll[int](
    name="shots", side=Side.THIS_MODEL, kernel=_none_or_two, target=Scalar("t", 1)
)
_spent_die = Roll[int](name="roll", side=Side.THIS_MODEL, kernel=_d6, target=Scalar("t", 6))
_spent = Program.build(
    "spent",
    _SIDES,
    (_spent_shots, Repeat(name="attack", times=_spent_shots, items=(_spent_die,))),
)


def _spent_six(world: Trace) -> int:
    return 1 if world.of(_spent_die) == 6 else 0


_spent_die.show(Projection("sixes", _spent_six, Monoid(0)))


def test_a_group_that_may_not_run_stacks_the_empty_tally() -> None:
    (lane,) = _spent.evaluate()
    stacked = lane.read(_spent_die, Projection("sixes", _spent_six, Monoid(0)))
    shown = lane.to_view()["nodes"][1]["edge"]["readings"][0]["outcomes"]

    assert stacked.mass == {
        0: Fraction(61, 72),
        1: Fraction(10, 72),
        2: Fraction(1, 72),
    }
    assert shown[0] == {"value": 0, "p": 61 / 72}


def _one_or_two() -> Distribution[int]:
    return Distribution({1: _HALF, 2: _HALF})


def _wound_on(hit: int) -> Distribution[bool]:
    through = Fraction(hit, 3)
    return Distribution({True: through, False: 1 - through})


_once = Measurement[int](name="attacks", side=Side.THIS_MODEL, kernel=_one)
_hit = Roll[int](
    name="roll-to-hit", side=Side.THIS_MODEL, kernel=_one_or_two, target=Scalar("t", 1)
)
_wound = Roll[bool](
    name="roll-to-wound",
    side=Side.THIS_MODEL,
    inputs=(_hit,),
    kernel=_wound_on,
    target=Scalar("t", 1),
)
_coupled = Program.build(
    "coupled",
    _SIDES,
    (_once, Repeat(name="attack", times=_once, items=(_hit, _wound))),
)


def _both(world: Trace) -> tuple[int | bool, ...]:
    return world.of(_hit), world.of(_wound)


def test_a_reading_over_a_pair_keeps_the_coupling() -> None:
    (lane,) = _coupled.evaluate()
    joint = lane.read(
        _wound, Projection("hit and wound", _both, Monoid[tuple[int | bool, ...]](()))
    )
    hits = lane.read(_wound, _hit.output("hit", Monoid(0)))
    wounds = lane.read(_wound, _wound.output("wound", Monoid(False)))

    assert joint.mass == {
        (1, True): Fraction(1, 6),
        (1, False): Fraction(1, 3),
        (2, True): Fraction(1, 3),
        (2, False): Fraction(1, 6),
    }
    assert hits.mass == {1: _HALF, 2: _HALF}
    assert wounds.mass == {True: _HALF, False: _HALF}
    assert joint.mass[1, True] != hits.mass[1] * wounds.mass[True]


def _strong(strength: int) -> Distribution[int]:
    return Distribution({face: _SIXTH for face in range(strength, strength + 6)})


def test_a_step_reads_an_enclosing_block() -> None:
    attacks = Measurement[int](name="attacks", side=Side.THIS_MODEL, kernel=_one)
    strength = Measurement[int](name="strength", side=Side.THIS_MODEL, kernel=_three)
    wound = Roll[int](
        name="roll-to-wound",
        side=Side.THIS_MODEL,
        inputs=(strength,),
        kernel=_strong,
        target=Scalar("t", 4),
    )
    program = Program.build(
        "volley",
        _SIDES,
        (attacks, strength, Repeat(name="attack", times=attacks, items=(wound,))),
    )
    (lane,) = program.evaluate()
    faces = lane.read(wound, wound.output("face", Monoid(0)))

    assert faces.mass == {face: _SIXTH for face in range(3, 9)}


def _toll(face: int) -> Distribution[int]:
    return Distribution.pure(face)


def test_a_step_cannot_read_inside_a_nested_block() -> None:
    shots = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_three)
    hit = Roll[int](name="roll-to-hit", side=Side.THIS_MODEL, kernel=_d6, target=Scalar("t", 4))
    removed = Consequence[int](
        name="remove-casualties", side=Side.THE_ENEMY, inputs=(hit,), kernel=_toll
    )

    with pytest.raises(GraphError, match="roll-to-hit, which is not in scope"):
        Program.build(
            "volley",
            _SIDES,
            (shots, Repeat(name="attack", times=shots, items=(hit,)), removed),
        )


def test_a_group_cannot_run_a_count_out_of_scope() -> None:
    hidden = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_three)
    hit = Roll[int](name="roll-to-hit", side=Side.THIS_MODEL, kernel=_d6, target=Scalar("t", 4))

    with pytest.raises(GraphError, match="runs shots times, which is not in scope"):
        Program.build("volley", _SIDES, (Repeat(name="attack", times=hidden, items=(hit,)),))


def _no_inputs() -> Distribution[int]:
    return Distribution.pure(3)


def _two_inputs(first: int, second: int) -> Distribution[int]:
    return Distribution.pure(first + second)


@pytest.mark.parametrize("kernel", [_no_inputs, _two_inputs])
def test_a_kernel_must_accept_its_inputs(kernel: Callable[..., Distribution[int]]) -> None:
    source = Measurement[int](name="source", side=Side.THIS_MODEL, kernel=_three)
    dependent = Measurement[int](
        name="dependent", side=Side.THIS_MODEL, inputs=(source,), kernel=kernel
    )

    with pytest.raises(GraphError, match="kernel cannot accept 1 positional inputs"):
        Program.build("arity", _SIDES, (source, dependent))


def test_two_steps_cannot_share_a_path() -> None:
    first = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_three)
    second = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_three)

    with pytest.raises(GraphError, match="volley/shots is declared twice"):
        Program.build("volley", _SIDES, (first, second))


def _ground(reaction: str) -> Distribution[int]:
    return Distribution.pure(0 if reaction == "hold" else 6)


def _fight() -> tuple[Program, Decision[str], Consequence[int]]:
    reaction = Decision[str](
        name="declare-reaction", side=Side.THE_ENEMY, options=("hold", "flee")
    )
    given = Consequence[int](
        name="ground-given", side=Side.THE_ENEMY, inputs=(reaction,), kernel=_ground
    )
    program = Program.build(
        "charge",
        _SIDES,
        (reaction, Lanes(name="reaction", decision=reaction, items=(given,))),
    )
    return program, reaction, given


def test_an_open_decision_splits_the_program_into_lanes() -> None:
    program, reaction, given = _fight()
    lanes = program.evaluate()
    ground = [lane.read(given, given.output("ground", Monoid(0))).mass for lane in lanes]

    assert len(lanes) == 2
    assert ground == [{0: 1}, {6: 1}]
    assert [lane.choices[reaction] for lane in lanes] == ["hold", "flee"]


def test_a_fixed_decision_leaves_one_lane() -> None:
    program, reaction, given = _fight()
    (lane,) = program.evaluate(choices={reaction: "flee"})

    assert lane.read(given, given.output("ground", Monoid(0))).mass == {6: 1}
    assert lane.to_view()["lanes"] == [{"decision": "charge/declare-reaction", "outcome": "flee"}]


def test_an_unknown_decision_is_rejected() -> None:
    program, _, _ = _fight()
    stray = Decision[str](name="stray", side=Side.THIS_MODEL, options=("yes",))

    with pytest.raises(GraphError, match="stray is not a decision in charge"):
        program.evaluate(choices={stray: "yes"})


def test_an_invalid_decision_choice_is_rejected() -> None:
    program, reaction, _ = _fight()

    with pytest.raises(GraphError, match="'charge' is not an option for declare-reaction"):
        program.evaluate(choices={reaction: "charge"})


def test_a_rule_cannot_land_on_a_step_the_program_lacks() -> None:
    program, reaction, given = _fight()
    stray = Measurement[int](name="stray", side=Side.THIS_MODEL, kernel=_three)

    with pytest.raises(GraphError, match="lands on stray, which is not declared"):
        program.attach(
            RuleNode(
                rule="hatred",
                name="Hatred",
                bearer=Bearer.THIS_MODEL,
                landings=(Landing(stray, Verdict.HELD),),
            )
        )


def _hit_on(range_band: str) -> Distribution[int]:
    return _d6()


def _removed(range_band: str) -> Distribution[int]:
    return Distribution.pure(1 if range_band == "close" else 0)


_shots = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_three)
_range = Decision[str](name="choose-range", side=Side.THIS_MODEL, options=("close", "long"))
_to_hit = Roll[int](
    name="roll-to-hit",
    side=Side.THIS_MODEL,
    inputs=(_range,),
    kernel=_hit_on,
    target=Scalar("to hit", 4),
    modifiers=(Modifier("Volley Fire", 1),),
)
_casualties = Consequence[int](
    name="remove-casualties", side=Side.THE_ENEMY, inputs=(_range,), kernel=_removed
)
_stomp = Slot(name="stomp", items=())
_volley = Program.build(
    "volley",
    _SIDES,
    (
        _shots,
        _range,
        Repeat(name="attack", times=_shots, items=(_to_hit,)),
        _stomp,
        Lanes(name="aftermath", decision=_range, items=(_casualties,)),
    ),
)


def _landed(world: Trace) -> int:
    return 1 if world.of(_to_hit) >= 4 else 0


_shots.show(_shots.output("shots", Monoid(0)))
_to_hit.show(Projection("hits", _landed, Monoid(0)))
_casualties.show(Scalar("models", 5))
_volley.attach(
    RuleNode(
        rule="volley-fire",
        name="Volley Fire",
        bearer=Bearer.THIS_MODEL,
        landings=(
            Landing(_to_hit, Verdict.APPLIED),
            Landing(_casualties, Verdict.HONOURED),
        ),
    )
)
_volley.attach(RuleNode(rule="stubborn", name="Stubborn", bearer=Bearer.CORE))


def _view() -> dict[str, Any]:
    (lane,) = _volley.evaluate(choices={_range: "close"})
    return lane.to_view()


def test_a_rule_node_lists_its_landings() -> None:
    rules = _view()["rules"]

    assert rules[0]["landings"] == [
        {"at": "volley/attack/roll-to-hit", "verdict": "applied"},
        {"at": "volley/aftermath/remove-casualties", "verdict": "honoured"},
    ]
    assert rules[1] == {"rule": "stubborn", "name": "Stubborn", "bearer": "core", "landings": []}


def test_the_view_carries_the_blocks_and_the_stacked_readings() -> None:
    view = _view()
    hits = next(node for node in view["nodes"] if node["step"] == "roll-to-hit")

    assert view["blocks"] == [
        {"path": "volley/attack", "kind": "repeat", "times": "volley/shots", "collapsed": False},
        {"path": "volley/stomp", "kind": "slot", "empty": True},
        {"path": "volley/aftermath", "kind": "lanes", "decision": "volley/choose-range"},
    ]
    assert hits["inputs"] == ["volley/choose-range"]
    assert hits["target"] == {"label": "to hit", "value": 4}
    assert hits["modifiers"] == [{"rule": "Volley Fire", "move": 1}]
    assert hits["edge"]["readings"][0]["outcomes"] == [
        {"value": 0, "p": 0.125},
        {"value": 1, "p": 0.375},
        {"value": 2, "p": 0.375},
        {"value": 3, "p": 0.125},
    ]


_TYPES = Path(__file__).resolve().parents[2] / "frontend/src/lib/graph/types.ts"
_NODE_OF = {step.kind: step.__name__ for step in (Measurement, Decision, Roll, Consequence)}
_BLOCK_OF = {block.kind: block.__name__ for block in (Sequence, Repeat, Slot, Lanes)}


def _declared() -> dict[str, set[str]]:
    text = _TYPES.read_text()
    fields: dict[str, set[str]] = {}
    for match in re.finditer(r"interface (\w+)(?: extends (\w+))?\s*\{(.*?)\n\}", text, re.S):
        name, parent, body = match.groups()
        own = set(re.findall(r"^\s*(\w+)\??:", body, re.M))
        fields[name] = own | fields.get(parent, set())
    return fields


def _reading_shape(reading: dict[str, Any], declared: dict[str, set[str]]) -> None:
    assert set(reading) in (declared["Distribution"], declared["Scalar"])
    for outcome in reading.get("outcomes", ()):
        assert set(outcome) == declared["Outcome"]


def test_the_view_matches_the_front_end_types() -> None:
    declared = _declared()
    view = _view()

    assert set(view) == declared["Program"]
    for node in view["nodes"]:
        assert set(node) == declared[_NODE_OF[node["kind"]]]
        assert set(node["edge"]) == declared["Edge"]
        for reading in node["edge"]["readings"]:
            _reading_shape(reading, declared)
        for modifier in node.get("modifiers", ()):
            assert set(modifier) == declared["Modifier"]
    for block in view["blocks"]:
        assert set(block) == declared[_BLOCK_OF[block["kind"]]]
    for rule in view["rules"]:
        assert set(rule) == declared["Rule"]
        for landing in rule["landings"]:
            assert set(landing) == declared["Landing"]
    for lane in view["lanes"]:
        assert set(lane) == declared["Lane"]


def test_the_front_end_declares_the_interfaces_the_view_fills() -> None:
    declared = _declared()

    assert declared["Program"] == {"program", "sides", "nodes", "blocks", "rules", "lanes"}
    assert declared["Roll"] > declared["Step"]
