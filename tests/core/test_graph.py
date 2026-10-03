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
    State,
    Verdict,
    World,
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


def _six(face: int) -> int:
    return 1 if face == 6 else 0


def test_a_roll_edge_carries_its_own_distribution() -> None:
    flip = Roll[int](name="flip", side=Side.THIS_MODEL, kernel=_coin, target=Scalar("target", 1))
    face = flip.output("face", Monoid(0))
    flip.show(face)
    program = Program.build("coin", _SIDES, (flip,))

    (lane,) = program.evaluate()

    assert lane.read(flip, face).mass == {0: _HALF, 1: _HALF}


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
_certain_sixes = Projection("sixes", (_certain_die,), _six, Monoid(0))
_certain_die.show(_certain_sixes)
_certain = Program.build(
    "certain",
    _SIDES,
    (_certain_shots, Repeat(name="attack", times=_certain_shots, items=(_certain_die,))),
)


def test_a_reading_stacks_a_certain_count() -> None:
    (lane,) = _certain.evaluate()
    stacked = lane.read(_certain_die, _certain_sixes)

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
_open_sixes = Projection("sixes", (_open_die,), _six, Monoid(0))
_open_die.show(_open_sixes)
_open = Program.build(
    "open",
    _SIDES,
    (_open_shots, Repeat(name="attack", times=_open_shots, items=(_open_die,))),
)


def test_a_reading_stacks_an_uncertain_count() -> None:
    (lane,) = _open.evaluate()
    stacked = lane.read(_open_die, _open_sixes)

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
_spent_sixes = Projection("sixes", (_spent_die,), _six, Monoid(0))
_spent_die.show(_spent_sixes)
_spent = Program.build(
    "spent",
    _SIDES,
    (_spent_shots, Repeat(name="attack", times=_spent_shots, items=(_spent_die,))),
)


def test_a_group_that_may_not_run_stacks_the_empty_tally() -> None:
    (lane,) = _spent.evaluate()
    stacked = lane.read(_spent_die, _spent_sixes)
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


def _both(hit: int, wound: bool) -> tuple[int | bool, ...]:
    return hit, wound


_hit_and_wound = Projection(
    "hit and wound", (_hit, _wound), _both, Monoid[tuple[int | bool, ...]](())
)
_hits = _hit.output("hit", Monoid(0))
_wounds = _wound.output("wound", Monoid(False))
_wound.show(_hit_and_wound)
_wound.show(_hits)
_wound.show(_wounds)
_coupled = Program.build(
    "coupled",
    _SIDES,
    (_once, Repeat(name="attack", times=_once, items=(_hit, _wound))),
)


def test_a_reading_over_a_pair_keeps_the_coupling() -> None:
    (lane,) = _coupled.evaluate()
    joint = lane.read(_wound, _hit_and_wound)
    hits = lane.read(_wound, _hits)
    wounds = lane.read(_wound, _wounds)

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
    face = wound.output("face", Monoid(0))
    wound.show(face)
    program = Program.build(
        "volley",
        _SIDES,
        (attacks, strength, Repeat(name="attack", times=attacks, items=(wound,))),
    )
    (lane,) = program.evaluate()
    faces = lane.read(wound, face)

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


def test_a_reading_cannot_show_a_step_out_of_scope() -> None:
    shots = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_three)
    hit = Roll[int](name="roll-to-hit", side=Side.THIS_MODEL, kernel=_d6, target=Scalar("t", 4))
    removed = Measurement[int](name="remove-casualties", side=Side.THE_ENEMY, kernel=_three)
    removed.show(hit.output("hits", Monoid(0)))

    with pytest.raises(GraphError, match="shows roll-to-hit, which is not in scope"):
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


def test_an_unread_output_dies_at_its_own_edge() -> None:
    unread = Measurement[int](name="unread", side=Side.THIS_MODEL, kernel=_d6)
    shown = Measurement[int](name="shown", side=Side.THIS_MODEL, kernel=_d6)
    shown.show(shown.output("face", Monoid(0)))
    (lane,) = Program.build("dice", _SIDES, (unread, shown)).evaluate()

    assert len(lane.edges[unread].joint.mass) == 1
    assert len(lane.edges[shown].joint.mass) == 6


def test_only_a_declared_reading_can_be_read() -> None:
    flip = Measurement[int](name="flip", side=Side.THIS_MODEL, kernel=_coin)
    (lane,) = Program.build("coin", _SIDES, (flip,)).evaluate()

    with pytest.raises(GraphError, match="face is not a reading of flip"):
        lane.read(flip, flip.output("face", Monoid(0)))


def test_a_reading_shown_after_build_is_refused() -> None:
    flip = Measurement[int](name="flip", side=Side.THIS_MODEL, kernel=_coin)
    program = Program.build("coin", _SIDES, (flip,))
    flip.show(flip.output("face", Monoid(0)))

    with pytest.raises(GraphError, match="coin/flip was shown a reading after build"):
        program.evaluate()


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


def _add_three(total: int) -> Distribution[int]:
    return Distribution.pure(total + 3)


def _add_four(total: int) -> Distribution[int]:
    return Distribution.pure(total + 4)


def _same(value: int) -> int:
    return value


def test_a_state_write_replaces_the_fact() -> None:
    total = State[int]("total")
    first = Consequence[int](
        name="add-three", side=Side.THIS_MODEL, inputs=(total,), kernel=_add_three, writes=total
    )
    second = Consequence[int](
        name="add-four", side=Side.THIS_MODEL, inputs=(total,), kernel=_add_four, writes=total
    )
    sums = Projection("total", (total,), _same, Monoid(0))
    second.show(sums)
    (lane,) = Program.build("tally", _SIDES, (first, second)).evaluate(state={total: 0})

    assert lane.read(second, sums).mass == {7: 1}


def test_a_fact_read_before_it_is_written_must_be_given() -> None:
    total = State[int]("total")
    stray = State[int]("stray")
    add = Consequence[int](
        name="add-three", side=Side.THIS_MODEL, inputs=(total,), kernel=_add_three, writes=total
    )
    program = Program.build("tally", _SIDES, (add,))

    with pytest.raises(GraphError, match="tally reads total before writing it"):
        program.evaluate()
    with pytest.raises(GraphError, match="stray is not a state fact of tally"):
        program.evaluate(state={total: 0, stray: 0})


def test_a_state_writing_step_shows_its_own_output() -> None:
    total = State[int]("total")
    add = Consequence[int](
        name="add-three", side=Side.THIS_MODEL, inputs=(total,), kernel=_add_three, writes=total
    )
    added = add.output("total", Monoid(0))
    add.show(added)
    (lane,) = Program.build("tally", _SIDES, (add,)).evaluate(state={total: 0})

    assert lane.read(add, added).mass == {3: 1}


def test_worlds_holding_the_same_values_are_equal_whatever_the_write_order() -> None:
    fleeing = State[bool]("fleeing")
    models = State[int]("models")

    first = World().holding(fleeing, True).holding(models, 4)
    second = World().holding(models, 4).holding(fleeing, True)

    assert first == second


def _lose(models: int, hit: int) -> Distribution[int]:
    return Distribution.pure(models - hit)


def _pair(models: int, hit: int) -> Distribution[tuple[int, int]]:
    return Distribution.pure((models, hit))


def test_a_slot_keeps_its_locals_and_its_state_writes() -> None:
    models = State[int]("models")
    hit = Measurement[int](name="hit", side=Side.THIS_MODEL, kernel=_coin)
    remove = Consequence[int](
        name="remove-casualties",
        side=Side.THE_ENEMY,
        inputs=(models, hit),
        kernel=_lose,
        writes=models,
    )
    after = Consequence[tuple[int, int]](
        name="after", side=Side.THE_ENEMY, inputs=(models, hit), kernel=_pair
    )
    pair = after.output("after", Monoid((0, 0)))
    after.show(pair)
    program = Program.build("round", _SIDES, (Slot(name="shooting", items=(hit, remove)), after))
    (lane,) = program.evaluate(state={models: 5})

    assert lane.read(after, pair).mass == {
        (5, 0): _HALF,
        (4, 1): _HALF,
    }


def test_a_lane_keeps_its_state_writes() -> None:
    models = State[int]("models")
    reaction = Decision[str](name="declare-reaction", side=Side.THE_ENEMY, options=("hold",))
    hit = Measurement[int](name="hit", side=Side.THIS_MODEL, kernel=_coin)
    remove = Consequence[int](
        name="remove-casualties",
        side=Side.THE_ENEMY,
        inputs=(models, hit),
        kernel=_lose,
        writes=models,
    )
    after = Consequence[int](name="after", side=Side.THE_ENEMY, inputs=(models,), kernel=_toll)
    left = after.output("models", Monoid(0))
    after.show(left)
    program = Program.build(
        "charge",
        _SIDES,
        (reaction, Lanes(name="reaction", decision=reaction, items=(hit, remove)), after),
    )
    (lane,) = program.evaluate(state={models: 5})

    assert lane.read(after, left).mass == {5: _HALF, 4: _HALF}


def test_a_lane_local_is_out_of_scope_after_it() -> None:
    reaction = Decision[str](name="declare-reaction", side=Side.THE_ENEMY, options=("hold",))
    hit = Measurement[int](name="hit", side=Side.THIS_MODEL, kernel=_coin)
    after = Consequence[int](name="after", side=Side.THE_ENEMY, inputs=(hit,), kernel=_toll)

    with pytest.raises(GraphError, match="after inputs hit, which is not in scope"):
        Program.build(
            "charge",
            _SIDES,
            (reaction, Lanes(name="reaction", decision=reaction, items=(hit,)), after),
        )


def test_a_repeat_holds_inside_only_what_its_inside_reads() -> None:
    outer = Measurement[int](name="outer", side=Side.THIS_MODEL, kernel=_d6)
    shots = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_one_or_two)
    roll = Measurement[int](name="roll", side=Side.THIS_MODEL, kernel=_d6)
    roll.show(roll.output("face", Monoid(0)))
    later = Consequence[int](name="later", side=Side.THIS_MODEL, inputs=(outer,), kernel=_toll)
    attack = Repeat(name="attack", times=shots, items=(roll,))
    (lane,) = Program.build("volley", _SIDES, (outer, shots, attack, later)).evaluate()

    assert len(lane.edges[roll].joint.mass) == 6


def test_a_repeat_exit_drops_what_only_its_inside_read() -> None:
    shots = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_one_or_two)
    roll = Measurement[int](name="roll", side=Side.THIS_MODEL, kernel=_d6)
    attack = Repeat(name="attack", times=shots, items=(roll,))
    (lane,) = Program.build("volley", _SIDES, (shots, attack)).evaluate()

    assert len(lane.joint.mass) == 1


def test_a_repeat_cannot_write_state() -> None:
    models = State[int]("models")
    shots = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_three)
    hit = Measurement[int](name="hit", side=Side.THIS_MODEL, kernel=_coin)
    remove = Consequence[int](
        name="remove-casualties",
        side=Side.THE_ENEMY,
        inputs=(models, hit),
        kernel=_lose,
        writes=models,
    )

    with pytest.raises(GraphError, match="remove-casualties writes models inside a repeat"):
        Program.build(
            "volley", _SIDES, (shots, Repeat(name="attack", times=shots, items=(hit, remove)))
        )


def _add(total: int, face: int) -> Distribution[int]:
    return Distribution.pure(total + face)


def test_a_running_total_holds_only_the_total_between_rolls() -> None:
    total = State[int]("total")
    items: list[Measurement[int] | Consequence[int]] = []
    for throw in range(1, 5):
        roll = Measurement[int](name=f"roll-{throw}", side=Side.THIS_MODEL, kernel=_d6)
        add = Consequence[int](
            name=f"add-{throw}",
            side=Side.THIS_MODEL,
            inputs=(total, roll),
            kernel=_add,
            writes=total,
        )
        items += [roll, add]
    sums = Projection("total", (total,), _same, Monoid(0))
    items[-1].show(sums)
    (lane,) = Program.build("sum", _SIDES, tuple(items)).evaluate(state={total: 0})

    assert [len(lane.edges[step].joint.mass) for step in items] == [6, 6, 36, 11, 66, 16, 96, 21]
    assert lane.read(items[-1], sums).mass[14] == Fraction(146, 6**4)


def test_the_view_lists_only_steps_as_inputs() -> None:
    total = State[int]("total")
    roll = Measurement[int](name="roll", side=Side.THIS_MODEL, kernel=_d6)
    add = Consequence[int](
        name="add", side=Side.THIS_MODEL, inputs=(total, roll), kernel=_add, writes=total
    )
    (lane,) = Program.build("sum", _SIDES, (roll, add)).evaluate(state={total: 0})

    assert [node["inputs"] for node in lane.to_view()["nodes"]] == [[], ["sum/roll"]]


def _up_to_five() -> Distribution[int]:
    return Distribution({wounds: _SIXTH for wounds in range(6)})


def _remove(models: int, wounds: int) -> Distribution[int]:
    return Distribution.pure(max(models - wounds, 0))


def _round(number: int, models: State[int]) -> tuple[Slot, Consequence[int]]:
    wounds = Measurement[int](name="wounds", side=Side.THIS_MODEL, kernel=_up_to_five)
    removal = Consequence[int](
        name="remove-casualties",
        side=Side.THE_ENEMY,
        inputs=(models, wounds),
        kernel=_remove,
        writes=models,
    )
    return Slot(name=f"round-{number}", items=(wounds, removal)), removal


def test_six_casualty_removals_keep_one_world_per_standing() -> None:
    models = State[int]("models")
    rounds = [_round(number, models) for number in range(1, 7)]
    last = rounds[-1][1]
    left = Projection("models", (models,), _same, Monoid(0))
    last.show(left)
    program = Program.build("attrition", _SIDES, tuple(slot for slot, _ in rounds))
    (lane,) = program.evaluate(state={models: 22})

    assert len(lane.edges[last].joint.mass) == 23
    assert lane.read(last, left).mass[22] == Fraction(1, 6**6)


def _band() -> Distribution[str]:
    return Distribution({"close": _HALF, "long": _HALF})


def _two() -> Distribution[int]:
    return Distribution.pure(2)


def _hits_only_close(band: str) -> Distribution[int]:
    return Distribution.pure(1 if band == "close" else 0)


def test_a_group_stacks_its_attacks_per_outer_world() -> None:
    band = Measurement[str](name="range", side=Side.THIS_MODEL, kernel=_band)
    shots = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_two)
    hit = Roll[int](
        name="roll-to-hit",
        side=Side.THIS_MODEL,
        inputs=(band,),
        kernel=_hits_only_close,
        target=Scalar("to hit", 4),
    )
    hits = hit.output("hits", Monoid(0))
    hit.show(hits)
    attack = Repeat(name="attack", times=shots, items=(hit,))
    (lane,) = Program.build("volley", _SIDES, (band, shots, attack)).evaluate()

    assert lane.read(hit, hits).mass == {0: _HALF, 2: _HALF}


def test_a_repeat_inside_a_repeat_is_refused() -> None:
    once = Measurement[int](name="once", side=Side.THIS_MODEL, kernel=_one)
    hit = Measurement[int](name="hit", side=Side.THIS_MODEL, kernel=_coin)
    inner = Repeat(name="inner", times=once, items=(hit,))

    with pytest.raises(GraphError, match="fight/outer/inner repeats inside fight/outer"):
        Program.build("fight", _SIDES, (once, Repeat(name="outer", times=once, items=(inner,))))


def test_two_steps_cannot_share_a_path() -> None:
    first = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_three)
    second = Measurement[int](name="shots", side=Side.THIS_MODEL, kernel=_three)

    with pytest.raises(GraphError, match="volley/shots is declared twice"):
        Program.build("volley", _SIDES, (first, second))


def _ground(reaction: str) -> Distribution[int]:
    return Distribution.pure(0 if reaction == "hold" else 6)


def _fight() -> tuple[Program, Decision[str], Consequence[int], Projection[int]]:
    reaction = Decision[str](
        name="declare-reaction", side=Side.THE_ENEMY, options=("hold", "flee")
    )
    given = Consequence[int](
        name="ground-given", side=Side.THE_ENEMY, inputs=(reaction,), kernel=_ground
    )
    ground = given.output("ground", Monoid(0))
    given.show(ground)
    program = Program.build(
        "charge",
        _SIDES,
        (reaction, Lanes(name="reaction", decision=reaction, items=(given,))),
    )
    return program, reaction, given, ground


def test_an_open_decision_splits_the_program_into_lanes() -> None:
    program, reaction, given, ground = _fight()
    lanes = program.evaluate()
    given_up = [lane.read(given, ground).mass for lane in lanes]

    assert len(lanes) == 2
    assert given_up == [{0: 1}, {6: 1}]
    assert [lane.choices[reaction] for lane in lanes] == ["hold", "flee"]


def test_a_fixed_decision_leaves_one_lane() -> None:
    program, reaction, given, ground = _fight()
    (lane,) = program.evaluate(choices={reaction: "flee"})

    assert lane.read(given, ground).mass == {6: 1}
    assert lane.to_view()["lanes"] == [{"decision": "charge/declare-reaction", "outcome": "flee"}]


def test_an_unknown_decision_is_rejected() -> None:
    program, _, _, _ = _fight()
    stray = Decision[str](name="stray", side=Side.THIS_MODEL, options=("yes",))

    with pytest.raises(GraphError, match="stray is not a decision in charge"):
        program.evaluate(choices={stray: "yes"})


def test_an_invalid_decision_choice_is_rejected() -> None:
    program, reaction, _, _ = _fight()

    with pytest.raises(GraphError, match="'charge' is not an option for declare-reaction"):
        program.evaluate(choices={reaction: "charge"})


def test_a_rule_cannot_land_on_a_step_the_program_lacks() -> None:
    program, _, _, _ = _fight()
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


def _landed(face: int) -> int:
    return 1 if face >= 4 else 0


_shots.show(_shots.output("shots", Monoid(0)))
_to_hit.show(Projection("hits", (_to_hit,), _landed, Monoid(0)))
_casualties.show(Scalar("models", 5))
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
