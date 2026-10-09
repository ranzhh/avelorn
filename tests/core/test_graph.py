import re
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from avelorn.core.distribution import Distribution, Monoid
from avelorn.core.graph import (
    Body,
    By,
    Carrier,
    Change,
    Consequence,
    Contribution,
    Decision,
    Eligibility,
    GraphError,
    Holder,
    Key,
    Landing,
    Mark,
    Measurement,
    Operation,
    Order,
    Program,
    Projection,
    Repeat,
    Roll,
    RuleNode,
    Scalar,
    Sequence,
    Slot,
    Source,
    State,
    Step,
    Taken,
    Tally,
    Verdict,
    World,
)

_SIXTH = Fraction(1, 6)
_HALF = Fraction(1, 2)
_SIDES = ("attacker", "target")
_ATTACKER = Holder("attacker", "archers")
_TARGET = Holder("target", "spearmen")
_MODEL = (Source(Carrier.MODEL),)
_CORE = (Source(Carrier.CORE),)


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


def _always(*values: Any) -> bool:
    return True


def _runs(step: Step[int]) -> Projection[int]:
    return step.output("times", Monoid(0))


@dataclass(frozen=True)
class _Shift:
    """A toy change that moves a roll by ``by`` in each world where ``when`` holds."""

    by: int
    reads: tuple[Key, ...] = ()
    when: Callable[..., bool] = _always
    order: Order = Order.ADD

    def settle(self, values: tuple[Any, ...], out: frozenset[str]) -> Hashable | None:
        return self.by if self.when(*values) else None

    def cancels(self, other: Change) -> bool:
        return False

    def view(self) -> dict[str, Any]:
        return {"text": f"{self.by:+d}"}


@dataclass(frozen=True)
class _Cancel:
    """A toy cancel that removes ``of`` in each world where ``when`` holds."""

    of: Change
    reads: tuple[Key, ...] = ()
    when: Callable[..., bool] = _always
    order: Order = Order.CANCEL

    def settle(self, values: tuple[Any, ...], out: frozenset[str]) -> Hashable | None:
        return "cancel" if self.when(*values) else None

    def cancels(self, other: Change) -> bool:
        return other is self.of

    def view(self) -> dict[str, Any]:
        return {"text": "cancel"}


def test_a_roll_edge_carries_its_own_distribution() -> None:
    flip = Roll[int](name="flip", side="attacker", kernel=_coin, target=Scalar("target", 1))
    face = flip.output("face", Monoid(0))
    flip.show(face)
    program = Program.build("coin", _SIDES, (flip,))

    (lane,) = program.evaluate()

    assert lane.read(flip, face).mass == {0: _HALF, 1: _HALF}


def test_a_path_is_the_step_place_in_the_block_tree() -> None:
    shots = Measurement[int](name="shots", side="attacker", kernel=_three)
    hit = Roll[int](name="roll-to-hit", side="attacker", kernel=_d6, target=Scalar("t", 4))
    attack = Repeat(name="attack", times=_runs(shots), items=(hit,))
    program = Program.build("volley", _SIDES, (shots, attack))

    assert program.paths[shots] == "volley/shots"
    assert program.paths[attack] == "volley/attack"
    assert program.paths[hit] == "volley/attack/roll-to-hit"
    assert program.steps == [shots, hit]
    assert program.blocks == [attack]


_certain_shots = Measurement[int](name="shots", side="attacker", kernel=_three)
_certain_die = Roll[int](name="roll", side="attacker", kernel=_d6, target=Scalar("t", 6))
_certain_sixes = Projection("sixes", (_certain_die,), _six, Monoid(0))
_certain_die.show(_certain_sixes)
_certain = Program.build(
    "certain",
    _SIDES,
    (_certain_shots, Repeat(name="attack", times=_runs(_certain_shots), items=(_certain_die,))),
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


_open_shots = Roll[int](name="shots", side="attacker", kernel=_two_or_three, target=Scalar("t", 1))
_open_die = Roll[int](name="roll", side="attacker", kernel=_d6, target=Scalar("t", 6))
_open_sixes = Projection("sixes", (_open_die,), _six, Monoid(0))
_open_die.show(_open_sixes)
_open = Program.build(
    "open",
    _SIDES,
    (_open_shots, Repeat(name="attack", times=_runs(_open_shots), items=(_open_die,))),
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


_spent_shots = Roll[int](name="shots", side="attacker", kernel=_none_or_two, target=Scalar("t", 1))
_spent_die = Roll[int](name="roll", side="attacker", kernel=_d6, target=Scalar("t", 6))
_spent_sixes = Projection("sixes", (_spent_die,), _six, Monoid(0))
_spent_die.show(_spent_sixes)
_spent = Program.build(
    "spent",
    _SIDES,
    (_spent_shots, Repeat(name="attack", times=_runs(_spent_shots), items=(_spent_die,))),
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


_once = Measurement[int](name="attacks", side="attacker", kernel=_one)
_hit = Roll[int](name="roll-to-hit", side="attacker", kernel=_one_or_two, target=Scalar("t", 1))
_wound = Roll[bool](
    name="roll-to-wound",
    side="attacker",
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
    (_once, Repeat(name="attack", times=_runs(_once), items=(_hit, _wound))),
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
    attacks = Measurement[int](name="attacks", side="attacker", kernel=_one)
    strength = Measurement[int](name="strength", side="attacker", kernel=_three)
    wound = Roll[int](
        name="roll-to-wound",
        side="attacker",
        inputs=(strength,),
        kernel=_strong,
        target=Scalar("t", 4),
    )
    face = wound.output("face", Monoid(0))
    wound.show(face)
    program = Program.build(
        "volley",
        _SIDES,
        (attacks, strength, Repeat(name="attack", times=_runs(attacks), items=(wound,))),
    )
    (lane,) = program.evaluate()
    faces = lane.read(wound, face)

    assert faces.mass == {face: _SIXTH for face in range(3, 9)}


def _toll(face: int) -> Distribution[int]:
    return Distribution.pure(face)


def test_a_step_cannot_read_inside_a_nested_block() -> None:
    shots = Measurement[int](name="shots", side="attacker", kernel=_three)
    hit = Roll[int](name="roll-to-hit", side="attacker", kernel=_d6, target=Scalar("t", 4))
    removed = Consequence[int](
        name="remove-casualties", side="target", inputs=(hit,), kernel=_toll
    )

    with pytest.raises(GraphError, match="roll-to-hit, which is not in scope"):
        Program.build(
            "volley",
            _SIDES,
            (shots, Repeat(name="attack", times=_runs(shots), items=(hit,)), removed),
        )


def test_a_reading_cannot_show_a_step_out_of_scope() -> None:
    shots = Measurement[int](name="shots", side="attacker", kernel=_three)
    hit = Roll[int](name="roll-to-hit", side="attacker", kernel=_d6, target=Scalar("t", 4))
    removed = Measurement[int](name="remove-casualties", side="target", kernel=_three)
    removed.show(hit.output("hits", Monoid(0)))

    with pytest.raises(GraphError, match="shows roll-to-hit, which is not in scope"):
        Program.build(
            "volley",
            _SIDES,
            (shots, Repeat(name="attack", times=_runs(shots), items=(hit,)), removed),
        )


def test_a_group_cannot_run_a_count_out_of_scope() -> None:
    hidden = Measurement[int](name="shots", side="attacker", kernel=_three)
    hit = Roll[int](name="roll-to-hit", side="attacker", kernel=_d6, target=Scalar("t", 4))

    with pytest.raises(GraphError, match="runs shots times, which is not in scope"):
        Program.build(
            "volley", _SIDES, (Repeat(name="attack", times=_runs(hidden), items=(hit,)),)
        )


def test_an_unread_output_dies_at_its_own_edge() -> None:
    unread = Measurement[int](name="unread", side="attacker", kernel=_d6)
    shown = Measurement[int](name="shown", side="attacker", kernel=_d6)
    shown.show(shown.output("face", Monoid(0)))
    (lane,) = Program.build("dice", _SIDES, (unread, shown)).evaluate()

    assert len(lane.edges[unread].joint.mass) == 1
    assert len(lane.edges[shown].joint.mass) == 6


def test_only_a_declared_reading_can_be_read() -> None:
    flip = Measurement[int](name="flip", side="attacker", kernel=_coin)
    (lane,) = Program.build("coin", _SIDES, (flip,)).evaluate()

    with pytest.raises(GraphError, match="face is not a reading of flip"):
        lane.read(flip, flip.output("face", Monoid(0)))


def test_a_reading_shown_after_build_is_refused() -> None:
    flip = Measurement[int](name="flip", side="attacker", kernel=_coin)
    program = Program.build("coin", _SIDES, (flip,))
    flip.show(flip.output("face", Monoid(0)))

    with pytest.raises(GraphError, match="coin/flip was shown a reading after build"):
        program.evaluate()


def _no_inputs() -> Distribution[int]:
    return Distribution.pure(3)


def _two_inputs(first: int, second: int) -> Distribution[int]:
    return Distribution.pure(first + second)


def _a_mark_read_first(source: Step[int], changed: Mark[tuple[Hashable, ...]]) -> Step[Any]:
    return Measurement[int](
        name="marked",
        side="attacker",
        inputs=(changed, source),
        changed=changed,
        kernel=_two_inputs,
    )


def _a_mark_on_a_decision(source: Step[int], changed: Mark[tuple[Hashable, ...]]) -> Step[Any]:
    return Decision[str](
        name="marked",
        side="attacker",
        inputs=(changed,),
        changed=changed,
        options={"hold": (), "flee": ()},
        otherwise="hold",
    )


@pytest.mark.parametrize(
    ("marked", "message"),
    [
        (_a_mark_read_first, "marked/marked marks marked but does not read it last"),
        (_a_mark_on_a_decision, "marked/marked marks marked, but a decision settles options"),
    ],
)
def test_a_mark_the_kernel_does_not_read_last_is_refused(
    marked: Callable[[Step[int], Mark[tuple[Hashable, ...]]], Step[Any]], message: str
) -> None:
    source = Measurement[int](name="source", side="attacker", kernel=_three)
    step = marked(source, Mark[tuple[Hashable, ...]]("marked"))

    with pytest.raises(GraphError, match=re.escape(message)):
        Program.build("marked", _SIDES, (source, step))


@pytest.mark.parametrize("kernel", [_no_inputs, _two_inputs])
def test_a_kernel_must_accept_its_inputs(kernel: Callable[..., Distribution[int]]) -> None:
    source = Measurement[int](name="source", side="attacker", kernel=_three)
    dependent = Measurement[int](
        name="dependent", side="attacker", inputs=(source,), kernel=kernel
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
        name="add-three", side="attacker", inputs=(total,), kernel=_add_three, writes=total
    )
    second = Consequence[int](
        name="add-four", side="attacker", inputs=(total,), kernel=_add_four, writes=total
    )
    sums = Projection("total", (total,), _same, Monoid(0))
    second.show(sums)
    (lane,) = Program.build("tally", _SIDES, (first, second)).evaluate(state={total: 0})

    assert lane.read(second, sums).mass == {7: 1}


def test_a_fact_read_before_it_is_written_must_be_given() -> None:
    total = State[int]("total")
    stray = State[int]("stray")
    add = Consequence[int](
        name="add-three", side="attacker", inputs=(total,), kernel=_add_three, writes=total
    )
    program = Program.build("tally", _SIDES, (add,))

    with pytest.raises(GraphError, match="tally reads total before writing it"):
        program.evaluate()
    with pytest.raises(GraphError, match="stray is not a state fact of tally"):
        program.evaluate(state={total: 0, stray: 0})


def test_a_state_writing_step_shows_its_own_output() -> None:
    total = State[int]("total")
    add = Consequence[int](
        name="add-three", side="attacker", inputs=(total,), kernel=_add_three, writes=total
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
    hit = Measurement[int](name="hit", side="attacker", kernel=_coin)
    remove = Consequence[int](
        name="remove-casualties",
        side="target",
        inputs=(models, hit),
        kernel=_lose,
        writes=models,
    )
    after = Consequence[tuple[int, int]](
        name="after", side="target", inputs=(models, hit), kernel=_pair
    )
    pair = after.output("after", Monoid((0, 0)))
    after.show(pair)
    program = Program.build("round", _SIDES, (Slot(name="shooting", items=(hit, remove)), after))
    (lane,) = program.evaluate(state={models: 5})

    assert lane.read(after, pair).mass == {
        (5, 0): _HALF,
        (4, 1): _HALF,
    }


def test_a_body_keeps_its_state_writes() -> None:
    models = State[int]("models")
    hit = Measurement[int](name="hit", side="attacker", kernel=_coin)
    remove = Consequence[int](
        name="remove-casualties",
        side="target",
        inputs=(models, hit),
        kernel=_lose,
        writes=models,
    )
    reaction = Decision[str](
        name="declare-reaction",
        side="target",
        options={"hold": (hit, remove)},
        otherwise="hold",
    )
    after = Consequence[int](name="after", side="target", inputs=(models,), kernel=_toll)
    left = after.output("models", Monoid(0))
    after.show(left)
    program = Program.build("charge", _SIDES, (reaction, after))
    (lane,) = program.evaluate(state={models: 5})

    assert lane.read(after, left).mass == {5: _HALF, 4: _HALF}


def test_a_body_local_is_out_of_scope_after_it() -> None:
    hit = Measurement[int](name="hit", side="attacker", kernel=_coin)
    reaction = Decision[str](
        name="declare-reaction", side="target", options={"hold": (hit,)}, otherwise="hold"
    )
    after = Consequence[int](name="after", side="target", inputs=(hit,), kernel=_toll)

    with pytest.raises(GraphError, match="after inputs hit, which is not in scope"):
        Program.build("charge", _SIDES, (reaction, after))


def test_a_repeat_holds_inside_only_what_its_inside_reads() -> None:
    outer = Measurement[int](name="outer", side="attacker", kernel=_d6)
    shots = Measurement[int](name="shots", side="attacker", kernel=_one_or_two)
    roll = Measurement[int](name="roll", side="attacker", kernel=_d6)
    roll.show(roll.output("face", Monoid(0)))
    later = Consequence[int](name="later", side="attacker", inputs=(outer,), kernel=_toll)
    attack = Repeat(name="attack", times=_runs(shots), items=(roll,))
    (lane,) = Program.build("volley", _SIDES, (outer, shots, attack, later)).evaluate()

    assert len(lane.edges[roll].stacks.mass) == 2


def test_a_repeat_exit_drops_what_only_its_inside_read() -> None:
    shots = Measurement[int](name="shots", side="attacker", kernel=_one_or_two)
    roll = Measurement[int](name="roll", side="attacker", kernel=_d6)
    attack = Repeat(name="attack", times=_runs(shots), items=(roll,))
    (lane,) = Program.build("volley", _SIDES, (shots, attack)).evaluate()

    assert len(lane.joint.mass) == 1


def test_a_repeat_cannot_write_state() -> None:
    models = State[int]("models")
    shots = Measurement[int](name="shots", side="attacker", kernel=_three)
    hit = Measurement[int](name="hit", side="attacker", kernel=_coin)
    remove = Consequence[int](
        name="remove-casualties",
        side="target",
        inputs=(models, hit),
        kernel=_lose,
        writes=models,
    )

    with pytest.raises(GraphError, match="remove-casualties writes models inside a repeat"):
        Program.build(
            "volley",
            _SIDES,
            (shots, Repeat(name="attack", times=_runs(shots), items=(hit, remove))),
        )


def _add(total: int, face: int) -> Distribution[int]:
    return Distribution.pure(total + face)


def test_a_running_total_holds_only_the_total_between_rolls() -> None:
    total = State[int]("total")
    items: list[Measurement[int] | Consequence[int]] = []
    for throw in range(1, 5):
        roll = Measurement[int](name=f"roll-{throw}", side="attacker", kernel=_d6)
        add = Consequence[int](
            name=f"add-{throw}",
            side="attacker",
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
    roll = Measurement[int](name="roll", side="attacker", kernel=_d6)
    add = Consequence[int](
        name="add", side="attacker", inputs=(total, roll), kernel=_add, writes=total
    )
    (lane,) = Program.build("sum", _SIDES, (roll, add)).evaluate(state={total: 0})

    assert [node["inputs"] for node in lane.to_view()["nodes"]] == [[], ["sum/roll"]]


def _up_to_five() -> Distribution[int]:
    return Distribution({wounds: _SIXTH for wounds in range(6)})


def _remove(models: int, wounds: int) -> Distribution[int]:
    return Distribution.pure(max(models - wounds, 0))


def _round(number: int, models: State[int]) -> tuple[Slot, Consequence[int]]:
    wounds = Measurement[int](name="wounds", side="attacker", kernel=_up_to_five)
    removal = Consequence[int](
        name="remove-casualties",
        side="target",
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
    band = Measurement[str](name="range", side="attacker", kernel=_band)
    shots = Measurement[int](name="shots", side="attacker", kernel=_two)
    hit = Roll[int](
        name="roll-to-hit",
        side="attacker",
        inputs=(band,),
        kernel=_hits_only_close,
        target=Scalar("to hit", 4),
    )
    hits = hit.output("hits", Monoid(0))
    hit.show(hits)
    attack = Repeat(name="attack", times=_runs(shots), items=(hit,))
    (lane,) = Program.build("volley", _SIDES, (band, shots, attack)).evaluate()

    assert lane.read(hit, hits).mass == {0: _HALF, 2: _HALF}


def _charged() -> Distribution[bool]:
    return Distribution({True: _HALF, False: _HALF})


def _attackers(charged: bool) -> Distribution[int]:
    return Distribution.pure(2 if charged else 0)


def _hit_if_charged(charged: bool) -> Distribution[int]:
    if not charged:
        return Distribution.pure(0)
    return Distribution({1: Fraction(5, 6), 0: _SIXTH})


def _left_after(models: int, wounds: int) -> Distribution[int]:
    return Distribution.pure(max(models - wounds, 0))


def _charged_and_models(charged: bool, models: int) -> tuple[bool, int]:
    return (charged, models)


def test_remove_casualties_reads_the_tally_of_its_own_world() -> None:
    """Uncharged, nobody attacks; charged, two attackers hit on 5/6 each.

    Two hits: 1/2 * (5/6)^2 = 25/72. One hit: 1/2 * 2 * 5/6 * 1/6 = 5/36.
    No hit: 1/2 + 1/2 * (1/6)^2 = 37/72.
    """
    models = State[int]("models")
    charged = Measurement[bool](name="charged", side="attacker", kernel=_charged)
    attackers = Measurement[int](
        name="attackers", side="attacker", inputs=(charged,), kernel=_attackers
    )
    hit = Roll[int](
        name="roll-to-hit",
        side="attacker",
        inputs=(charged,),
        kernel=_hit_if_charged,
        target=Scalar("to hit", 2),
    )
    hits = hit.output("hits", Monoid(0))
    hit.show(hits)
    attack = Repeat(name="attack", times=_runs(attackers), items=(hit,))
    tally = Tally[int]("hits", {attack: hits})
    remove = Consequence[int](
        name="remove-casualties",
        side="target",
        inputs=(models, tally),
        kernel=_left_after,
        writes=models,
    )
    left = Projection("models", (models,), _same, Monoid(0))
    standing = Projection[tuple[bool, int]](
        "charged and models", (charged, models), _charged_and_models, Monoid((False, 0))
    )
    remove.show(left)
    remove.show(standing)
    program = Program.build("fight", _SIDES, (charged, attackers, attack, remove))
    (lane,) = program.evaluate(state={models: 5})

    assert lane.read(hit, hits).mass == {
        0: Fraction(37, 72),
        1: Fraction(5, 36),
        2: Fraction(25, 72),
    }
    assert lane.read(remove, left).mass == {
        5: Fraction(37, 72),
        4: Fraction(5, 36),
        3: Fraction(25, 72),
    }
    assert lane.read(remove, standing).mass == {
        (False, 5): _HALF,
        (True, 5): Fraction(1, 72),
        (True, 4): Fraction(5, 36),
        (True, 3): Fraction(25, 72),
    }


def test_a_tally_sums_every_group_it_counts() -> None:
    models = State[int]("models")
    charged = Measurement[bool](name="charged", side="attacker", kernel=_charged)
    once = Measurement[int](name="once", side="attacker", kernel=_one)
    rider = Measurement[int](
        name="rider-hit", side="attacker", inputs=(charged,), kernel=_hits_on_the_charge
    )
    mount = Measurement[int](
        name="mount-hit", side="attacker", inputs=(charged,), kernel=_hits_on_the_charge
    )
    riders = Repeat(name="riders", times=_runs(once), items=(rider,))
    mounts = Repeat(name="mounts", times=_runs(once), items=(mount,))
    hits = Tally[int](
        "hits",
        {mounts: mount.output("hits", Monoid(0)), riders: rider.output("hits", Monoid(0))},
    )
    remove = Consequence[int](
        name="remove-casualties",
        side="target",
        inputs=(models, hits),
        kernel=_left_after,
        writes=models,
    )
    left = Projection("models", (models,), _same, Monoid(0))
    remove.show(left)
    slot = Slot(name="initiative-4", items=(riders, mounts, remove))
    (lane,) = Program.build("fight", _SIDES, (charged, once, slot)).evaluate(state={models: 5})

    assert lane.read(remove, left).mass == {5: _HALF, 3: _HALF}


def _hits_on_the_charge(charged: bool) -> Distribution[int]:
    return Distribution.pure(int(charged))


def _two_and_three() -> Distribution[tuple[int, int]]:
    return Distribution.pure((2, 3))


def _first(counts: tuple[int, int]) -> int:
    return counts[0]


def _second(counts: tuple[int, int]) -> int:
    return counts[1]


def test_repeats_sharing_one_count_tally_as_one_repeat_of_the_whole() -> None:
    counts = Measurement[tuple[int, int]](name="counts", side="attacker", kernel=_two_and_three)
    first_flip = Measurement[int](name="flip", side="attacker", kernel=_coin)
    second_flip = Measurement[int](name="flip", side="attacker", kernel=_coin)
    first = Repeat(
        name="first",
        times=Projection("times", (counts,), _first, Monoid(0)),
        items=(first_flip,),
    )
    second = Repeat(
        name="second",
        times=Projection("times", (counts,), _second, Monoid(0)),
        items=(second_flip,),
    )
    heads = Tally[int](
        "heads",
        {
            first: first_flip.output("heads", Monoid(0)),
            second: second_flip.output("heads", Monoid(0)),
        },
    )
    summed = Consequence[int](name="sum", side="attacker", inputs=(heads,), kernel=_toll)
    total = summed.output("heads", Monoid(0))
    summed.show(total)
    attack = Sequence(name="attack", items=(first, second))
    program = Program.build("toy", _SIDES, (counts, attack, summed))

    (lane,) = program.evaluate()

    assert lane.read(summed, total).mass == _coin().repeat(5, Monoid(0)).mass
    assert [first.view(program.paths), second.view(program.paths)] == [
        {"path": "toy/attack/first", "kind": "repeat", "times": "toy/counts", "collapsed": False},
        {"path": "toy/attack/second", "kind": "repeat", "times": "toy/counts", "collapsed": False},
    ]


def test_a_tally_of_a_group_out_of_scope_is_refused() -> None:
    once = Measurement[int](name="once", side="attacker", kernel=_one)
    hit = Measurement[int](name="hit", side="attacker", kernel=_coin)
    attack = Repeat(name="attack", times=_runs(once), items=(hit,))
    reaction = Decision[str](
        name="declare-reaction", side="target", options={"hold": (attack,)}, otherwise="hold"
    )
    hits = Tally[int]("hits", {attack: hit.output("hits", Monoid(0))})
    remove = Consequence[int](
        name="remove-casualties", side="target", inputs=(hits,), kernel=_toll
    )

    with pytest.raises(GraphError, match="tallies attack, which is not in scope"):
        Program.build("charge", _SIDES, (once, reaction, remove))


type _Counts = dict[Repeat, Projection[Any]]


def _no_group(attack: Repeat, hit: Step[int], other: Repeat, miss: Step[int]) -> _Counts:
    return {}


def _groups_in_two_slots(
    attack: Repeat, hit: Step[int], other: Repeat, miss: Step[int]
) -> _Counts:
    return {attack: hit.output("hits", Monoid(0)), other: miss.output("hits", Monoid(0))}


def _mixed_aggregations(attack: Repeat, hit: Step[int], other: Repeat, miss: Step[int]) -> _Counts:
    return {attack: hit.output("hits", Monoid(0)), other: miss.output("hits", Monoid(0, max))}


def _a_projection_outside_its_group(
    attack: Repeat, hit: Step[int], other: Repeat, miss: Step[int]
) -> _Counts:
    return {other: hit.output("hits", Monoid(0))}


@pytest.mark.parametrize(
    ("counts", "same_slot", "refusal"),
    [
        (_no_group, True, "hits counts no group"),
        (_groups_in_two_slots, False, "hits sums groups from fight/i4, fight/i5"),
        (_mixed_aggregations, True, "hits sums its groups with different aggregations"),
        (_a_projection_outside_its_group, True, "hits counts hit, outside other"),
    ],
    ids=["no-group", "groups-in-two-slots", "mixed-aggregations", "projection-outside-group"],
)
def test_a_tally_that_cannot_be_summed_is_refused(
    counts: Callable[[Repeat, Step[int], Repeat, Step[int]], _Counts],
    same_slot: bool,
    refusal: str,
) -> None:
    once = Measurement[int](name="once", side="attacker", kernel=_one)
    hit = Measurement[int](name="hit", side="attacker", kernel=_coin)
    miss = Measurement[int](name="miss", side="attacker", kernel=_coin)
    attack = Repeat(name="attack", times=_runs(once), items=(hit,))
    other = Repeat(name="other", times=_runs(once), items=(miss,))
    hits = Tally[int]("hits", counts(attack, hit, other, miss))
    remove = Consequence[int](
        name="remove-casualties", side="target", inputs=(hits,), kernel=_toll
    )
    slots = (
        (Slot(name="i5", items=(attack, other, remove)),)
        if same_slot
        else (Slot(name="i5", items=(attack,)), Slot(name="i4", items=(other, remove)))
    )

    with pytest.raises(GraphError, match=re.escape(refusal)):
        Program.build("fight", _SIDES, (once, *slots))


def test_a_group_feeds_only_one_tally() -> None:
    once = Measurement[int](name="once", side="attacker", kernel=_one)
    hit = Measurement[int](name="hit", side="attacker", kernel=_coin)
    attack = Repeat(name="attack", times=_runs(once), items=(hit,))
    hits = Tally[int]("hits", {attack: hit.output("hits", Monoid(0))})
    wounds = Tally[int]("wounds", {attack: hit.output("wounds", Monoid(0))})
    remove = Consequence[int](
        name="remove-casualties", side="target", inputs=(hits,), kernel=_toll
    )
    result = Consequence[int](name="combat-result", side="target", inputs=(wounds,), kernel=_toll)

    with pytest.raises(GraphError, match="attack is tallied by hits already"):
        Program.build("fight", _SIDES, (once, attack, remove, result))


def test_a_repeat_inside_a_repeat_is_refused() -> None:
    once = Measurement[int](name="once", side="attacker", kernel=_one)
    hit = Measurement[int](name="hit", side="attacker", kernel=_coin)
    inner = Repeat(name="inner", times=_runs(once), items=(hit,))

    with pytest.raises(GraphError, match="fight/outer/inner repeats inside fight/outer"):
        Program.build(
            "fight", _SIDES, (once, Repeat(name="outer", times=_runs(once), items=(inner,)))
        )


def test_a_step_acting_for_a_side_the_program_lacks_is_refused() -> None:
    stray = Measurement[int](name="shots", side="defender", kernel=_three)

    with pytest.raises(GraphError, match="volley/shots acts for defender, no side of volley"):
        Program.build("volley", _SIDES, (stray,))


def test_two_steps_cannot_share_a_path() -> None:
    first = Measurement[int](name="shots", side="attacker", kernel=_three)
    second = Measurement[int](name="shots", side="attacker", kernel=_three)

    with pytest.raises(GraphError, match="volley/shots is declared twice"):
        Program.build("volley", _SIDES, (first, second))


def _ground(reaction: str) -> Distribution[int]:
    return Distribution.pure(0 if reaction == "hold" else 6)


def _fight() -> tuple[Program, Decision[str], Consequence[int], Projection[int]]:
    reaction = Decision[str](
        name="declare-reaction",
        side="target",
        options={"hold": (), "flee": ()},
        otherwise="hold",
    )
    given = Consequence[int](
        name="ground-given", side="target", inputs=(reaction,), kernel=_ground
    )
    ground = given.output("ground", Monoid(0))
    given.show(ground)
    program = Program.build("charge", _SIDES, (reaction, given))
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
    stray = Decision[str](name="stray", side="attacker", options={"yes": ()}, otherwise="yes")

    with pytest.raises(GraphError, match="stray is not a decision in charge"):
        program.evaluate(choices={stray: "yes"})


def test_an_invalid_decision_choice_is_rejected() -> None:
    program, reaction, _, _ = _fight()

    with pytest.raises(GraphError, match="'charge' is not an option for declare-reaction"):
        program.evaluate(choices={reaction: "charge"})


def test_a_rule_cannot_land_on_a_step_the_program_lacks() -> None:
    program, _, _, _ = _fight()
    stray = Measurement[int](name="stray", side="attacker", kernel=_three)

    with pytest.raises(GraphError, match="lands on stray, which is not declared"):
        program.attach(
            (
                RuleNode(
                    rule="hatred",
                    name="Hatred",
                    holder=_ATTACKER,
                    sources=_MODEL,
                    landings=(Landing(stray),),
                ),
            )
        )


def _three_or_nine() -> Distribution[int]:
    return Distribution({3: _HALF, 9: _HALF})


def _six_inches() -> Distribution[int]:
    return Distribution.pure(6)


def _a_bow() -> Distribution[frozenset[str]]:
    return Distribution.pure(frozenset({"bow"}))


def _one_falls_if_any_fired(weapons: frozenset[str], models: int) -> Distribution[int]:
    return Distribution.pure(models - 1 if weapons else models)


def _every_weapon_when_too_close(
    printed: frozenset[str], gap: int, movement: int
) -> frozenset[str]:
    return printed if gap < movement else frozenset()


def _hold_once_anyone_fired(printed: frozenset[str], weapons: frozenset[str]) -> frozenset[str]:
    return frozenset({"hold"} if weapons else ())


type _Reaction = tuple[
    Program, Decision[str], Decision[str], Eligibility[str], Projection[frozenset[str]]
]


def _charge_reaction() -> tuple[_Reaction, Consequence[int], Projection[int], State[int]]:
    chargers = State[int]("chargers")
    gap = Measurement[int](name="gap", side="target", kernel=_three_or_nine)
    movement = Measurement[int](name="movement", side="attacker", kernel=_six_inches)
    who = Eligibility[str](name="who-can-shoot", side="target", kernel=_a_bow)
    weapons = who.output("weapons", Monoid(frozenset[str]()))
    who.show(weapons)
    volley = Consequence[int](
        name="volley",
        side="target",
        inputs=(who, chargers),
        kernel=_one_falls_if_any_fired,
        writes=chargers,
    )
    instead = Decision[str](
        name="hold-or-flee-instead",
        side="target",
        options={"hold": (), "flee": ()},
        otherwise="hold",
    )
    reactions = Decision[str](
        name="charge-reactions",
        side="target",
        options={"hold": (), "stand-and-shoot": (who, volley, instead), "flee": ()},
        otherwise="hold",
    )
    charge = Consequence[int](name="charge", side="attacker", inputs=(chargers,), kernel=_toll)
    left = charge.output("chargers", Monoid(0))
    charge.show(left)
    program = Program.build("charge", _SIDES, (gap, movement, reactions, charge))
    program.attach(
        (
            RuleNode(
                rule="stand-and-shoot",
                name="Stand & Shoot",
                holder=_TARGET,
                sources=_CORE,
                landings=(
                    Landing(
                        who,
                        contributions=(
                            Contribution(
                                operation=Operation.FORBID,
                                inputs=(gap, movement),
                                options=_every_weapon_when_too_close,
                                text="forbid every weapon",
                            ),
                        ),
                    ),
                    Landing(
                        instead,
                        contributions=(
                            Contribution(
                                operation=Operation.FORCE,
                                inputs=(who,),
                                options=_hold_once_anyone_fired,
                                text="force hold",
                            ),
                        ),
                    ),
                ),
            ),
        )
    )
    return (program, reactions, instead, who, weapons), charge, left, chargers


def test_inside_the_charger_movement_nothing_fires_and_elsewhere_the_shooters_hold() -> None:
    (program, reactions, instead, who, weapons), charge, left, chargers = _charge_reaction()
    (lane,) = program.evaluate(
        choices={reactions: "stand-and-shoot", instead: "flee"}, state={chargers: 5}
    )

    assert lane.read(who, weapons).mass == {frozenset(): _HALF, frozenset({"bow"}): _HALF}
    assert lane.read(instead, instead.taken).mass == {
        Taken("flee", By.CHOSEN): _HALF,
        Taken("hold", By.ONLY): _HALF,
    }
    assert lane.read(charge, left).mass == {5: _HALF, 4: _HALF}
    assert lane.verdicts("target/spearmen/stand-and-shoot", instead).mass == {
        Verdict.HONOURED: _HALF,
        Verdict.APPLIED: _HALF,
    }


def test_a_decision_inside_an_option_splits_only_the_lanes_that_took_it() -> None:
    (program, _, _, _, _), _, _, chargers = _charge_reaction()
    lanes = program.evaluate(state={chargers: 5})

    assert [tuple(lane.choices.values()) for lane in lanes] == [
        ("hold",),
        ("stand-and-shoot", "hold"),
        ("stand-and-shoot", "flee"),
        ("flee",),
    ]


def test_an_option_no_world_took_runs_nothing_and_records_no_choice() -> None:
    (program, reactions, instead, who, weapons), _, _, chargers = _charge_reaction()
    (lane,) = program.evaluate(choices={reactions: "hold", instead: "flee"}, state={chargers: 5})
    ran = {node["step"]: node["ran"] for node in lane.to_view()["nodes"]}

    assert lane.choices == {reactions: "hold"}
    assert ran["who-can-shoot"] is False
    with pytest.raises(GraphError, match="charge/charge-reactions/stand-and-shoot/who-can-shoot"):
        lane.read(who, weapons)


def _stand_and_shoot_when_too_close(
    printed: frozenset[str], gap: int, movement: int
) -> frozenset[str]:
    return frozenset({"stand-and-shoot"} if gap < movement else ())


def test_a_world_whose_choice_is_forbidden_takes_the_printed_otherwise() -> None:
    gap = Measurement[int](name="gap", side="target", kernel=_three_or_nine)
    movement = Measurement[int](name="movement", side="attacker", kernel=_six_inches)
    reactions = Decision[str](
        name="charge-reactions",
        side="target",
        options={"stand-and-shoot": (), "flee": (), "hold": ()},
        otherwise="hold",
    )
    program = Program.build("charge", _SIDES, (gap, movement, reactions))
    too_close = Contribution(
        operation=Operation.FORBID,
        inputs=(gap, movement),
        options=_stand_and_shoot_when_too_close,
        text="forbid stand-and-shoot",
    )
    program.attach(
        (
            RuleNode(
                rule="too-close",
                name="Too Close",
                holder=_TARGET,
                sources=_CORE,
                landings=(Landing(reactions, contributions=(too_close,)),),
            ),
        )
    )
    (lane,) = program.evaluate(choices={reactions: "stand-and-shoot"})

    assert lane.read(reactions, reactions.taken).mass == {
        Taken("stand-and-shoot", By.CHOSEN): _HALF,
        Taken("hold", By.OTHERWISE): _HALF,
    }


def _hold_when_close(printed: frozenset[str], gap: int) -> frozenset[str]:
    return frozenset({"hold"} if gap < 6 else ())


def _hold_always(printed: frozenset[str], gap: int) -> frozenset[str]:
    return frozenset({"hold"})


type _Amends = tuple[tuple[Operation, Callable[[frozenset[str], int], frozenset[str]]], ...]


def _held(amends: _Amends) -> tuple[Program, Decision[str]]:
    gap = Measurement[int](name="gap", side="target", kernel=_three_or_nine)
    reaction = Decision[str](
        name="charge-reactions",
        side="target",
        options={"hold": (), "flee": ()},
        otherwise="hold",
    )
    program = Program.build("charge", _SIDES, (gap, reaction))
    contributions = tuple(
        Contribution(operation=operation, inputs=(gap,), options=options, text=str(operation))
        for operation, options in amends
    )
    program.attach(
        (
            RuleNode(
                rule="must-hold",
                name="Must Hold",
                holder=_TARGET,
                sources=_CORE,
                landings=(Landing(reaction, contributions=contributions),),
            ),
        )
    )
    return program, reaction


@pytest.mark.parametrize(
    ("amends", "choice", "taken"),
    [
        (
            ((Operation.FORCE, _hold_when_close),),
            "flee",
            {Taken("hold", By.ONLY): _HALF, Taken("flee", By.CHOSEN): _HALF},
        ),
        (((Operation.FORCE, _hold_when_close),), "hold", {Taken("hold", By.CHOSEN): 1}),
        (
            ((Operation.FORBID, _hold_always), (Operation.FORCE, _hold_always)),
            "flee",
            {Taken("flee", By.CHOSEN): 1},
        ),
    ],
    ids=["force-narrows", "an-allowed-choice-beats-the-only-option", "force-needs-a-survivor"],
)
def test_a_force_narrows_what_a_world_may_take(
    amends: _Amends, choice: str, taken: dict[Taken[str], Fraction]
) -> None:
    program, reaction = _held(amends)
    (lane,) = program.evaluate(choices={reaction: choice})

    assert lane.read(reaction, reaction.taken).mass == taken


def test_a_decision_left_one_option_in_every_world_does_not_split() -> None:
    program, _ = _held(((Operation.FORCE, _hold_always),))

    (lane,) = program.evaluate()

    assert lane.choices == {}


def _fire_and_flee_when_far(printed: frozenset[str], gap: int) -> frozenset[str]:
    return frozenset({"fire-and-flee"} if gap >= 6 else ())


@pytest.mark.parametrize(
    ("opened", "lanes"),
    [(False, [("hold",), ("flee",)]), (True, [("hold",), ("flee",), ("fire-and-flee",)])],
    ids=["unopened", "opened-when-far"],
)
def test_a_closed_option_exists_only_where_a_rule_opens_it(
    opened: bool, lanes: list[tuple[str, ...]]
) -> None:
    gap = Measurement[int](name="gap", side="target", kernel=_three_or_nine)
    reaction = Decision[str](
        name="charge-reactions",
        side="target",
        options={"hold": (), "flee": (), "fire-and-flee": ()},
        closed=frozenset({"fire-and-flee"}),
        otherwise="hold",
    )
    program = Program.build("charge", _SIDES, (gap, reaction))
    opener = Contribution(
        operation=Operation.ALLOW,
        inputs=(gap,),
        options=_fire_and_flee_when_far,
        text="allow fire-and-flee",
    )
    if opened:
        program.attach(
            (
                RuleNode(
                    rule="fire-and-flee",
                    name="Fire & Flee",
                    holder=_TARGET,
                    sources=_MODEL,
                    landings=(Landing(reaction, contributions=(opener,)),),
                ),
            )
        )

    assert [tuple(lane.choices.values()) for lane in program.evaluate()] == lanes


def _pistol_when_too_close(printed: frozenset[str], gap: int, movement: int) -> frozenset[str]:
    return frozenset({"pistol"} if gap < movement else ())


def _a_pistol(printed: frozenset[str]) -> frozenset[str]:
    return frozenset({"pistol"})


def test_a_forbid_wins_over_an_allow_at_an_eligibility() -> None:
    gap = Measurement[int](name="gap", side="target", kernel=_three_or_nine)
    movement = Measurement[int](name="movement", side="attacker", kernel=_six_inches)
    who = Eligibility[str](name="who-can-shoot", side="target", kernel=_a_bow)
    weapons = who.output("weapons", Monoid(frozenset[str]()))
    who.show(weapons)
    program = Program.build("volley", _SIDES, (gap, movement, who))
    forbid = Contribution(
        operation=Operation.FORBID,
        inputs=(gap, movement),
        options=_pistol_when_too_close,
        text="forbid pistol",
    )
    allow = Contribution(operation=Operation.ALLOW, options=_a_pistol, text="allow pistol")
    program.attach(
        (
            RuleNode(
                rule="too-close",
                name="Too Close",
                holder=_TARGET,
                sources=_CORE,
                landings=(Landing(who, contributions=(forbid,)),),
            ),
        )
    )
    program.attach(
        (
            RuleNode(
                rule="brace-of-pistols",
                name="Brace of Pistols",
                holder=_TARGET,
                sources=_MODEL,
                landings=(Landing(who, contributions=(allow,)),),
            ),
        )
    )
    (lane,) = program.evaluate()

    assert lane.read(who, weapons).mass == {
        frozenset({"bow"}): _HALF,
        frozenset({"bow", "pistol"}): _HALF,
    }
    assert lane.verdicts("target/spearmen/too-close", who).mass == {
        Verdict.APPLIED: _HALF,
        Verdict.HONOURED: _HALF,
    }
    assert lane.verdicts("target/spearmen/brace-of-pistols", who).mass == {Verdict.APPLIED: 1}


def _ranks(changed: tuple[int, ...]) -> Distribution[frozenset[str]]:
    return Distribution.pure(frozenset(f"rank-{rank}" for rank in range(1, 2 + sum(changed))))


def _the_rank_behind(printed: frozenset[str]) -> frozenset[str]:
    return frozenset({f"rank-{len(printed) + 1}-supports"})


def test_an_eligibility_applies_an_add_before_its_allows() -> None:
    changed = Mark[tuple[Hashable, ...]]("who-can-fight")
    who = Eligibility[str](
        name="who-can-fight", side="attacker", inputs=(changed,), changed=changed, kernel=_ranks
    )
    ranks = who.output("ranks", Monoid(frozenset[str]()))
    who.show(ranks)
    program = Program.build("round", _SIDES, (who,))
    support = Contribution(
        operation=Operation.ALLOW, options=_the_rank_behind, text="allow the rank behind"
    )
    program.attach(
        (
            RuleNode(
                rule="deeper",
                name="Deeper",
                holder=_ATTACKER,
                sources=_MODEL,
                landings=(Landing(who, changes=(_Shift(1),)),),
            ),
            RuleNode(
                rule="support",
                name="Support",
                holder=_ATTACKER,
                sources=_MODEL,
                landings=(Landing(who, contributions=(support,)),),
            ),
        )
    )
    (lane,) = program.evaluate()

    assert lane.read(who, ranks).mass == {frozenset({"rank-1", "rank-2", "rank-3-supports"}): 1}
    verdicts = [lane.verdicts(f"attacker/archers/{rule}", who) for rule in ("deeper", "support")]
    assert [each.mass for each in verdicts] == [{Verdict.APPLIED: 1}, {Verdict.APPLIED: 1}]


def _hold(printed: frozenset[str]) -> frozenset[str]:
    return frozenset({"hold"})


def test_a_rule_the_player_may_decline_applies_only_in_the_lane_that_takes_it() -> None:
    reaction = Decision[str](
        name="charge-reactions",
        side="target",
        options={"hold": (), "flee": ()},
        otherwise="flee",
    )
    program = Program.build("charge", _SIDES, (reaction,))
    program.attach(
        (
            RuleNode(
                rule="stubborn",
                name="Stubborn",
                holder=_TARGET,
                sources=_MODEL,
                may=True,
                landings=(
                    Landing(
                        reaction,
                        contributions=(
                            Contribution(
                                operation=Operation.FORCE, options=_hold, text="force hold"
                            ),
                        ),
                    ),
                ),
            ),
        )
    )
    toggle = program.toggles["target", "stubborn"]

    lanes = program.evaluate(choices={reaction: "flee"})

    assert [
        (
            lane.choices[toggle],
            lane.read(reaction, reaction.taken).mass,
            lane.verdicts("target/spearmen/stubborn", reaction).mass,
        )
        for lane in lanes
    ] == [
        (True, {Taken("hold", By.ONLY): 1}, {Verdict.APPLIED: 1}),
        (False, {Taken("flee", By.CHOSEN): 1}, {Verdict.HONOURED: 1}),
    ]


def _marked_d6(changed: tuple[Hashable, ...]) -> Distribution[int]:
    return _d6()


def _marked_hit() -> Roll[int]:
    changed = Mark[tuple[Hashable, ...]]("roll-to-hit")
    return Roll[int](
        name="roll-to-hit",
        side="attacker",
        inputs=(changed,),
        changed=changed,
        kernel=_marked_d6,
        target=Scalar("t", 4),
    )


def test_one_rule_at_two_holders_is_two_nodes_judged_apart() -> None:
    hit = _marked_hit()
    program = Program.build("volley", _SIDES, (hit,))
    program.attach(
        (
            RuleNode(
                rule="hatred",
                name="Hatred",
                holder=_ATTACKER,
                sources=_MODEL,
                landings=(Landing(hit, changes=(_Shift(1),)),),
            ),
            RuleNode(
                rule="hatred",
                name="Hatred",
                holder=_TARGET,
                sources=_MODEL,
                landings=(Landing(hit),),
            ),
        )
    )
    (lane,) = program.evaluate()

    assert [(rule["id"], rule["landings"][0]["verdicts"]) for rule in lane.to_view()["rules"]] == [
        ("attacker/archers/hatred", [{"verdict": "applied", "p": 1.0}]),
        ("target/spearmen/hatred", [{"verdict": "held", "p": 1.0}]),
    ]


def test_a_node_granted_only_through_a_declined_node_is_honoured() -> None:
    hit = _marked_hit()
    program = Program.build("volley", _SIDES, (hit,))
    program.attach(
        (
            RuleNode(
                rule="skirmishers", name="Skirmishers", holder=_TARGET, sources=_MODEL, may=True
            ),
            RuleNode(
                rule="skirmish-formation",
                name="Skirmish Formation",
                holder=_TARGET,
                sources=(Source(Carrier.EFFECT, via="target/spearmen/skirmishers"),),
            ),
            RuleNode(
                rule="enemy-fire",
                name="Enemy Fire",
                holder=_TARGET,
                sources=(Source(Carrier.EFFECT, via="target/spearmen/skirmish-formation"),),
                landings=(Landing(hit, changes=(_Shift(-1),)),),
            ),
        )
    )
    toggle = program.toggles["target", "skirmishers"]

    assert [
        (lane.choices[toggle], lane.verdicts("target/spearmen/enemy-fire", hit).mass)
        for lane in program.evaluate()
    ] == [(True, {Verdict.APPLIED: 1}), (False, {Verdict.HONOURED: 1})]


def _hit_after(changed: tuple[int, ...]) -> Distribution[bool]:
    needed = 4 - sum(changed)
    return Distribution({True: Fraction(7 - needed, 6), False: Fraction(needed - 1, 6)})


def _heads(face: int) -> bool:
    return face == 1


def _paired(first: Hashable, hit: bool) -> tuple[Hashable, ...]:
    return first, hit


def test_a_gated_change_moves_only_the_worlds_where_its_gate_holds() -> None:
    coin = Measurement[int](name="coin", side="attacker", kernel=_coin)
    changed = Mark[tuple[Hashable, ...]]("hit")
    hit = Roll[bool](
        name="hit",
        side="attacker",
        inputs=(changed,),
        changed=changed,
        kernel=_hit_after,
        target=Scalar("t", 4),
    )
    both = Projection("both", (coin, hit), _paired, Monoid[tuple[Hashable, ...]](()))
    hit.show(both)
    program = Program.build("gated", _SIDES, (coin, hit))
    aim = Landing(hit, changes=(_Shift(1, reads=(coin,), when=_heads),))
    program.attach(
        (RuleNode(rule="aim", name="Aim", holder=_ATTACKER, sources=_MODEL, landings=(aim,)),)
    )

    (lane,) = program.evaluate()

    assert lane.verdicts("attacker/archers/aim", hit).mass == {
        Verdict.APPLIED: _HALF,
        Verdict.HONOURED: _HALF,
    }
    assert lane.read(hit, both).mass == {
        (0, True): Fraction(1, 4),
        (0, False): Fraction(1, 4),
        (1, True): Fraction(1, 3),
        (1, False): Fraction(1, 6),
    }


def _long(band: str) -> bool:
    return band == "long"


def test_a_cancel_removes_its_target_only_where_it_is_in_force() -> None:
    band = Measurement[str](name="check-range", side="attacker", kernel=_band)
    changed = Mark[tuple[Hashable, ...]]("hit")
    hit = Roll[bool](
        name="hit",
        side="attacker",
        inputs=(changed,),
        changed=changed,
        kernel=_hit_after,
        target=Scalar("t", 4),
    )
    both = Projection("both", (band, hit), _paired, Monoid[tuple[Hashable, ...]](()))
    hit.show(both)
    program = Program.build("cancelled", _SIDES, (band, hit))
    penalty = _Shift(-1)
    cloak = _Cancel(penalty, reads=(band,), when=_long)
    program.attach(
        (
            RuleNode(
                rule="far",
                name="Far",
                holder=_ATTACKER,
                sources=_MODEL,
                landings=(Landing(hit, changes=(penalty,)),),
            ),
            RuleNode(
                rule="cloak",
                name="Cloak",
                holder=_TARGET,
                sources=_MODEL,
                landings=(Landing(hit, changes=(cloak,)),),
            ),
        )
    )

    (lane,) = program.evaluate()

    assert lane.verdicts("attacker/archers/far", hit).mass == {
        Verdict.APPLIED: _HALF,
        Verdict.CANCELLED: _HALF,
    }
    assert lane.verdicts("target/spearmen/cloak", hit).mass == {
        Verdict.APPLIED: _HALF,
        Verdict.HONOURED: _HALF,
    }
    assert lane.read(hit, both).mass == {
        ("close", True): Fraction(1, 6),
        ("close", False): Fraction(1, 3),
        ("long", True): Fraction(1, 4),
        ("long", False): Fraction(1, 4),
    }


def test_a_cancel_with_nothing_to_remove_is_honoured() -> None:
    band = Measurement[str](name="check-range", side="attacker", kernel=_band)
    changed = Mark[tuple[Hashable, ...]]("hit")
    hit = Roll[bool](
        name="hit",
        side="attacker",
        inputs=(changed,),
        changed=changed,
        kernel=_hit_after,
        target=Scalar("t", 4),
    )
    program = Program.build("cancelled", _SIDES, (band, hit))
    penalty = _Shift(-1, reads=(band,), when=_long)
    program.attach(
        (
            RuleNode(
                rule="far",
                name="Far",
                holder=_ATTACKER,
                sources=_MODEL,
                landings=(Landing(hit, changes=(penalty,)),),
            ),
            RuleNode(
                rule="cloak",
                name="Cloak",
                holder=_TARGET,
                sources=_MODEL,
                landings=(Landing(hit, changes=(_Cancel(penalty),)),),
            ),
        )
    )

    (lane,) = program.evaluate()

    assert lane.verdicts("attacker/archers/far", hit).mass == {
        Verdict.CANCELLED: _HALF,
        Verdict.HONOURED: _HALF,
    }
    assert lane.verdicts("target/spearmen/cloak", hit).mass == {
        Verdict.APPLIED: _HALF,
        Verdict.HONOURED: _HALF,
    }


def _hit_count(hit: bool) -> int:
    return int(hit)


def test_a_rule_declined_inside_a_repeat_moves_nothing_in_its_lane() -> None:
    shots = Measurement[int](name="shots", side="attacker", kernel=_two)
    coin = Roll[int](name="coin", side="attacker", kernel=_coin, target=Scalar("t", 1))
    changed = Mark[tuple[Hashable, ...]]("hit")
    hit = Roll[bool](
        name="hit",
        side="attacker",
        inputs=(changed,),
        changed=changed,
        kernel=_hit_after,
        target=Scalar("t", 4),
    )
    hits = Projection("hits", (hit,), _hit_count, Monoid(0))
    hit.show(hits)
    attack = Repeat(name="attack", times=_runs(shots), items=(coin, hit))
    program = Program.build("aimed", _SIDES, (shots, attack))
    aim = Landing(hit, changes=(_Shift(1, reads=(coin,), when=_heads),))
    program.attach(
        (
            RuleNode(
                rule="aim",
                name="Aim",
                holder=_ATTACKER,
                sources=_MODEL,
                landings=(aim,),
                may=True,
            ),
        )
    )
    toggle = program.toggles["attacker", "aim"]

    assert [
        (
            lane.choices[toggle],
            lane.verdicts("attacker/archers/aim", hit).mass,
            lane.read(hit, hits).mass,
        )
        for lane in program.evaluate()
    ] == [
        (
            True,
            {Verdict.APPLIED: _HALF, Verdict.HONOURED: _HALF},
            {0: Fraction(25, 144), 1: Fraction(70, 144), 2: Fraction(49, 144)},
        ),
        (False, {Verdict.HONOURED: 1}, {0: Fraction(1, 4), 1: _HALF, 2: Fraction(1, 4)}),
    ]


def _one_or_two() -> Distribution[int]:
    return Distribution({1: Fraction(1, 3), 2: Fraction(2, 3)})


def _single(shots: int) -> bool:
    return shots == 1


def test_a_verdict_inside_a_repeat_weighs_the_worlds_that_enter_it() -> None:
    shots = Measurement[int](name="shots", side="attacker", kernel=_one_or_two)
    changed = Mark[tuple[Hashable, ...]]("hit")
    hit = Roll[bool](
        name="hit",
        side="attacker",
        inputs=(changed,),
        changed=changed,
        kernel=_hit_after,
        target=Scalar("t", 4),
    )
    attack = Repeat(name="attack", times=_runs(shots), items=(hit,))
    program = Program.build("aimed", _SIDES, (shots, attack))
    aim = Landing(hit, changes=(_Shift(1, reads=(shots,), when=_single),))
    program.attach(
        (RuleNode(rule="aim", name="Aim", holder=_ATTACKER, sources=_MODEL, landings=(aim,)),)
    )

    (lane,) = program.evaluate()

    assert lane.verdicts("attacker/archers/aim", hit).mass == {
        Verdict.APPLIED: Fraction(1, 3),
        Verdict.HONOURED: Fraction(2, 3),
    }


def _three_faces() -> Distribution[int]:
    return Distribution({face: Fraction(1, 3) for face in (1, 2, 3)})


def test_a_toggle_lane_keeps_its_masses_exact() -> None:
    die = Roll[int](name="die", side="target", kernel=_three_faces, target=Scalar("t", 1))
    face = die.output("face", Monoid(0))
    die.show(face)
    program = Program.build("toggled", _SIDES, (die,))
    program.attach(
        (RuleNode(rule="stubborn", name="Stubborn", holder=_TARGET, sources=_MODEL, may=True),)
    )

    third = Fraction(1, 3)
    assert [lane.read(die, face).mass for lane in program.evaluate()] == [
        {1: third, 2: third, 3: third},
        {1: third, 2: third, 3: third},
    ]


class _Counted:
    """A kernel that counts how often it runs."""

    def __init__(self) -> None:
        self.runs = 0

    def __call__(self) -> Distribution[int]:
        self.runs += 1
        return _d6()


def test_a_lane_splits_where_its_decision_is_reached() -> None:
    counted = _Counted()
    roll = Roll[int](name="roll", side="target", kernel=counted, target=Scalar("t", 1))
    reaction = Decision[str](
        name="declare-reaction", side="target", options={"hold": (), "flee": ()}, otherwise="hold"
    )
    program = Program.build("charge", _SIDES, (roll, reaction))

    lanes = program.evaluate()

    assert [lane.choices[reaction] for lane in lanes] == ["hold", "flee"]
    assert counted.runs == 1


def test_a_decision_inside_a_repeat_is_refused() -> None:
    once = Measurement[int](name="once", side="attacker", kernel=_one)
    weapon = Decision[str](name="weapon", side="attacker", options={"hand": ()}, otherwise="hand")

    with pytest.raises(
        GraphError, match="fight/attack/weapon settles options inside fight/attack"
    ):
        Program.build(
            "fight", _SIDES, (once, Repeat(name="attack", times=_runs(once), items=(weapon,)))
        )


def test_a_decision_that_writes_state_is_refused() -> None:
    reaction = Decision[str](
        name="charge-reactions",
        side="target",
        options={"hold": ()},
        otherwise="hold",
        writes=State[str]("reaction"),
    )

    with pytest.raises(GraphError, match="charge/charge-reactions writes reaction"):
        Program.build("charge", _SIDES, (reaction,))


def _charge_offered(printed: frozenset[str], gap: int) -> frozenset[str]:
    return frozenset({"charge"})


def _no_printed_set(gap: int) -> frozenset[str]:
    return frozenset()


def _node(
    landing: Landing | None = None,
    holder: Holder = _TARGET,
    sources: tuple[Source, ...] = _CORE,
    may: bool = False,
) -> RuleNode:
    landings = () if landing is None else (landing,)
    return RuleNode(rule="r", name="R", holder=holder, sources=sources, landings=landings, may=may)


def _marked_three(changed: tuple[Hashable, ...]) -> Distribution[int]:
    return _three()


def _refusal(case: str) -> tuple[Program, tuple[RuleNode, ...]]:
    gap = Measurement[int](name="gap", side="target", kernel=_three_or_nine)
    changed = Mark[tuple[Hashable, ...]]("aimed")
    aimed = Measurement[int](
        name="aimed", side="target", inputs=(changed,), changed=changed, kernel=_marked_three
    )
    after = Measurement[int](name="after", side="target", kernel=_three_or_nine)
    who = Eligibility[str](name="who-can-shoot", side="target", kernel=_a_bow)
    reaction = Decision[str](
        name="charge-reactions", side="target", options={"hold": ()}, otherwise="hold"
    )
    program = Program.build("charge", _SIDES, (gap, aimed, who, reaction, after))
    nodes = {
        "change-at-an-unmarked-step": (_node(Landing(gap, changes=(_Shift(1),))),),
        "change-reads-a-later-step": (
            _node(Landing(aimed, changes=(_Shift(1, reads=(after,)),))),
        ),
        "force-at-an-eligibility": (
            _node(
                Landing(
                    who,
                    (
                        Contribution(
                            operation=Operation.FORCE, options=_a_pistol, text="force pistol"
                        ),
                    ),
                )
            ),
        ),
        "contribution-arity": (
            _node(
                Landing(
                    reaction,
                    (
                        Contribution(
                            operation=Operation.ALLOW,
                            inputs=(gap,),
                            options=_no_printed_set,
                            text="allow nothing",
                        ),
                    ),
                )
            ),
        ),
        "contribution-reads-a-later-step": (
            _node(
                Landing(
                    reaction,
                    (
                        Contribution(
                            operation=Operation.ALLOW,
                            inputs=(after,),
                            options=_charge_offered,
                            text="allow charge",
                        ),
                    ),
                )
            ),
        ),
        "contribution-on-a-plain-step": (
            _node(
                Landing(
                    gap,
                    (
                        Contribution(
                            operation=Operation.ALLOW, options=_a_pistol, text="allow pistol"
                        ),
                    ),
                )
            ),
        ),
        "repeated-id": (_node(), _node()),
        "no-source": (_node(sources=()),),
        "unknown-holder-side": (_node(holder=Holder("defender", "spearmen")),),
        "via-naming-no-node": (
            _node(sources=(Source(Carrier.EFFECT, via="target/spearmen/stray"),)),
        ),
        "trigger-out-of-scope": (_node(Landing(gap, triggers=(after,))),),
        "may-with-only-core-sources": (_node(may=True),),
    }
    return program, nodes[case]


_REFUSALS = {
    "change-at-an-unmarked-step": "r changes charge/gap, which marks no changes",
    "change-reads-a-later-step": "r at charge/aimed reads after, not in scope",
    "force-at-an-eligibility": "forces charge/who-can-shoot, which only allow and forbid",
    "contribution-arity": "cannot accept the options and 1 inputs",
    "contribution-reads-a-later-step": "reads after, not in scope",
    "contribution-on-a-plain-step": "amends charge/gap, which settles no options",
    "repeated-id": "target/spearmen/r is attached to charge twice",
    "no-source": "target/spearmen/r has no source",
    "unknown-holder-side": "defender/spearmen/r is held by defender, no side of charge",
    "via-naming-no-node": "granted via target/spearmen/stray, which is no node",
    "trigger-out-of-scope": "r at charge/gap is triggered by after, not in scope",
    "may-with-only-core-sources": "target/spearmen/r is a core rule, which no player may decline",
}


@pytest.mark.parametrize(("case", "message"), list(_REFUSALS.items()), ids=list(_REFUSALS))
def test_a_node_the_program_cannot_take_is_refused_at_attach(case: str, message: str) -> None:
    program, nodes = _refusal(case)

    with pytest.raises(GraphError, match=re.escape(message)):
        program.attach(nodes)


def test_a_rule_offering_an_option_the_decision_lacks_is_refused() -> None:
    gap = Measurement[int](name="gap", side="target", kernel=_three_or_nine)
    reaction = Decision[str](
        name="charge-reactions", side="target", options={"hold": ()}, otherwise="hold"
    )
    program = Program.build("charge", _SIDES, (gap, reaction))
    offer = Contribution(
        operation=Operation.ALLOW, inputs=(gap,), options=_charge_offered, text="allow charge"
    )
    program.attach(
        (
            RuleNode(
                rule="stray",
                name="Stray",
                holder=_TARGET,
                sources=_CORE,
                landings=(Landing(reaction, contributions=(offer,)),),
            ),
        )
    )

    with pytest.raises(GraphError, match=re.escape("is offered ['charge']")):
        program.evaluate()


def _hit_on(range_band: str, changed: tuple[Hashable, ...]) -> Distribution[int]:
    return _d6()


def _stand_when_close(printed: frozenset[str], range_band: str) -> frozenset[str]:
    return frozenset({"stand"} if range_band == "close" else ())


_shots = Measurement[int](name="shots", side="attacker", kernel=_three)
_range = Decision[str](
    name="choose-range",
    side="attacker",
    options={"close": (), "long": ()},
    otherwise="close",
)
_to_hit_changed = Mark[tuple[Hashable, ...]]("roll-to-hit")
_to_hit = Roll[int](
    name="roll-to-hit",
    side="attacker",
    inputs=(_range, _to_hit_changed),
    changed=_to_hit_changed,
    kernel=_hit_on,
    target=Scalar("to hit", 4),
)
_casualties = Measurement[int](name="remove-casualties", side="target", kernel=_one)
_aftermath = Decision[str](
    name="aftermath",
    side="target",
    options={"stand": (_casualties,), "flee": ()},
    otherwise="flee",
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
        Repeat(name="attack", times=_runs(_shots), items=(_to_hit,)),
        _stomp,
        _aftermath,
    ),
)

_volley.attach(
    (
        RuleNode(
            rule="volley-fire",
            name="Volley Fire",
            holder=_ATTACKER,
            sources=_MODEL,
            landings=(
                Landing(_shots),
                Landing(_to_hit, changes=(_Shift(1),)),
                Landing(
                    _aftermath,
                    contributions=(
                        Contribution(
                            operation=Operation.FORCE,
                            inputs=(_range,),
                            options=_stand_when_close,
                            text="force stand",
                        ),
                    ),
                ),
            ),
        ),
    )
)
_volley.attach((RuleNode(rule="stubborn", name="Stubborn", holder=_TARGET, sources=_MODEL),))


def _view() -> dict[str, Any]:
    (lane,) = _volley.evaluate(choices={_range: "close"})
    return lane.to_view()


def test_a_rule_node_reads_its_verdicts_from_the_lane() -> None:
    rules = _view()["rules"]

    assert rules[0]["landings"] == [
        {"at": "volley/shots", "triggers": [], "verdicts": [{"verdict": "held", "p": 1.0}]},
        {
            "at": "volley/attack/roll-to-hit",
            "triggers": [],
            "verdicts": [{"verdict": "applied", "p": 1.0}],
        },
        {
            "at": "volley/aftermath",
            "triggers": [],
            "verdicts": [{"verdict": "applied", "p": 1.0}],
        },
    ]
    assert rules[1] == {
        "id": "target/spearmen/stubborn",
        "rule": "stubborn",
        "name": "Stubborn",
        "holder": {"side": "target", "part": "spearmen"},
        "may": False,
        "sources": [{"carrier": "model", "item": None, "profile": None, "via": None}],
        "landings": [],
    }


def test_the_view_carries_the_blocks_and_the_stacked_readings() -> None:
    view = _view()
    hits = next(node for node in view["nodes"] if node["step"] == "roll-to-hit")
    aftermath = next(node for node in view["nodes"] if node["step"] == "aftermath")

    assert view["blocks"] == [
        {"path": "volley/choose-range/close", "kind": "body", "decision": "volley/choose-range"},
        {"path": "volley/choose-range/long", "kind": "body", "decision": "volley/choose-range"},
        {"path": "volley/attack", "kind": "repeat", "times": "volley/shots", "collapsed": False},
        {"path": "volley/stomp", "kind": "slot", "empty": True},
        {"path": "volley/aftermath/stand", "kind": "body", "decision": "volley/aftermath"},
        {"path": "volley/aftermath/flee", "kind": "body", "decision": "volley/aftermath"},
    ]
    assert hits["inputs"] == ["volley/choose-range"]
    assert hits["target"] == {"label": "to hit", "value": 4}
    assert hits["changes"] == [{"rule": "attacker/archers/volley-fire", "text": "+1"}]
    assert hits["edge"]["readings"][0]["outcomes"] == [
        {"value": 0, "p": 0.125},
        {"value": 1, "p": 0.375},
        {"value": 2, "p": 0.375},
        {"value": 3, "p": 0.125},
    ]
    assert aftermath["inputs"] == ["volley/choose-range"]
    assert aftermath["edge"]["readings"] == [
        {"label": "taken", "outcomes": [{"value": "stand (only)", "p": 1.0}]}
    ]


_TYPES = Path(__file__).resolve().parents[2] / "frontend/src/lib/graph/types.ts"
_NODE_OF = {step.kind: step.__name__ for step in (Measurement, Decision, Roll, Consequence)}
_BLOCK_OF = {block.kind: block.__name__ for block in (Sequence, Repeat, Slot, Body)}


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
        for change in node["changes"]:
            assert set(change) == declared["Change"]
    for block in view["blocks"]:
        assert set(block) == declared[_BLOCK_OF[block["kind"]]]
    for rule in view["rules"]:
        assert set(rule) == declared["Rule"]
        assert set(rule["holder"]) == declared["Holder"]
        for source in rule["sources"]:
            assert set(source) == declared["Source"]
        for landing in rule["landings"]:
            assert set(landing) == declared["Landing"]
            for verdict in landing["verdicts"]:
                assert set(verdict) == declared["Judged"]
    for lane in view["lanes"]:
        assert set(lane) == declared["Lane"]


def test_the_front_end_declares_the_interfaces_the_view_fills() -> None:
    declared = _declared()

    assert declared["Program"] == {"program", "sides", "nodes", "blocks", "rules", "lanes"}
    assert declared["Roll"] > declared["Step"]
