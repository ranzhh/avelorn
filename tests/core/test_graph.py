from fractions import Fraction

import pytest

from avelorn.core.distribution import Distribution
from avelorn.core.graph import (
    Consequence,
    GraphError,
    Group,
    Measurement,
    Program,
    Projection,
    Roll,
    Scalar,
    Side,
    World,
)

_SIXTH = Fraction(1, 6)
_HALF = Fraction(1, 2)
_SIDES = {Side.THIS_MODEL: "the archers", Side.THE_ENEMY: "the spearmen"}


def _d6() -> Distribution[int]:
    return Distribution({face: _SIXTH for face in range(1, 7)})


def _coin() -> Distribution[int]:
    return Distribution({0: _HALF, 1: _HALF})


def _three() -> int:
    return 3


def _one() -> int:
    return 1


def test_a_roll_edge_carries_its_own_distribution() -> None:
    flip = Roll[int](name="flip", side=Side.THIS_MODEL, body=_coin, target=Scalar("target", 1))
    program = Program.build("coin", _SIDES, (flip,))

    assert program.evaluate().only().read(flip, flip.output("face")).mass == {0: _HALF, 1: _HALF}


def test_a_path_is_the_step_place_in_the_block_tree() -> None:
    shots = Measurement[int](name="shots", side=Side.THIS_MODEL, body=_three)
    hit = Roll[int](name="roll-to-hit", side=Side.THIS_MODEL, body=_d6, target=Scalar("t", 4))
    attack = Group(name="attack", times=shots, items=(hit,))
    program = Program.build("volley", _SIDES, (shots, attack))

    assert program.paths[shots] == "volley/shots"
    assert program.paths[attack] == "volley/attack"
    assert program.paths[hit] == "volley/attack/roll-to-hit"


_certain_shots = Measurement[int](name="shots", side=Side.THIS_MODEL, body=_three)
_certain_die = Roll[int](name="roll", side=Side.THIS_MODEL, body=_d6, target=Scalar("t", 6))
_certain = Program.build(
    "certain",
    _SIDES,
    (_certain_shots, Group(name="attack", times=_certain_shots, items=(_certain_die,))),
)


def _certain_six(world: World) -> int:
    return 1 if world.of(_certain_die) == 6 else 0


def test_a_reading_stacks_a_certain_count() -> None:
    stacked = _certain.evaluate().only().read(_certain_die, Projection("sixes", _certain_six))

    assert stacked.mass == {
        0: Fraction(125, 216),
        1: Fraction(75, 216),
        2: Fraction(15, 216),
        3: Fraction(1, 216),
    }


def _two_or_three() -> Distribution[int]:
    return Distribution({2: _HALF, 3: _HALF})


_open_shots = Roll[int](
    name="shots", side=Side.THIS_MODEL, body=_two_or_three, target=Scalar("t", 1)
)
_open_die = Roll[int](name="roll", side=Side.THIS_MODEL, body=_d6, target=Scalar("t", 6))
_open = Program.build(
    "open",
    _SIDES,
    (_open_shots, Group(name="attack", times=_open_shots, items=(_open_die,))),
)


def _open_six(world: World) -> int:
    return 1 if world.of(_open_die) == 6 else 0


def test_a_reading_stacks_an_uncertain_count() -> None:
    stacked = _open.evaluate().only().read(_open_die, Projection("sixes", _open_six))

    assert stacked.mass == {
        0: Fraction(275, 432),
        1: Fraction(135, 432),
        2: Fraction(21, 432),
        3: Fraction(1, 432),
    }


def _one_or_two() -> Distribution[int]:
    return Distribution({1: _HALF, 2: _HALF})


def _wound_on(hit: int) -> Distribution[bool]:
    through = Fraction(hit, 3)
    return Distribution({True: through, False: 1 - through})


_once = Measurement[int](name="attacks", side=Side.THIS_MODEL, body=_one)
_hit = Roll[int](name="roll-to-hit", side=Side.THIS_MODEL, body=_one_or_two, target=Scalar("t", 1))
_wound = Roll[bool](
    name="roll-to-wound",
    side=Side.THIS_MODEL,
    reads=(_hit,),
    body=_wound_on,
    target=Scalar("t", 1),
)
_coupled = Program.build(
    "coupled",
    _SIDES,
    (_once, Group(name="attack", times=_once, items=(_hit, _wound))),
)


def _both(world: World) -> tuple[int, bool]:
    return world.of(_hit), world.of(_wound)


def test_a_reading_over_a_pair_keeps_the_coupling() -> None:
    lane = _coupled.evaluate().only()
    joint = lane.read(_wound, Projection("hit and wound", _both))
    hits = lane.read(_wound, _hit.output("hit"))
    wounds = lane.read(_wound, _wound.output("wound"))

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
    attacks = Measurement[int](name="attacks", side=Side.THIS_MODEL, body=_one)
    strength = Measurement[int](name="strength", side=Side.THIS_MODEL, body=_three)
    wound = Roll[int](
        name="roll-to-wound",
        side=Side.THIS_MODEL,
        reads=(strength,),
        body=_strong,
        target=Scalar("t", 4),
    )
    program = Program.build(
        "volley",
        _SIDES,
        (attacks, strength, Group(name="attack", times=attacks, items=(wound,))),
    )
    faces = program.evaluate().only().read(wound, wound.output("face"))

    assert faces.mass == {face: _SIXTH for face in range(3, 9)}


def _toll(face: int) -> int:
    return face


def test_a_step_cannot_read_inside_a_nested_block() -> None:
    shots = Measurement[int](name="shots", side=Side.THIS_MODEL, body=_three)
    hit = Roll[int](name="roll-to-hit", side=Side.THIS_MODEL, body=_d6, target=Scalar("t", 4))
    removed = Consequence[int](
        name="remove-casualties", side=Side.THE_ENEMY, reads=(hit,), body=_toll
    )

    with pytest.raises(GraphError, match="roll-to-hit, which is not in scope"):
        Program.build(
            "volley",
            _SIDES,
            (shots, Group(name="attack", times=shots, items=(hit,)), removed),
        )


def test_a_group_cannot_run_a_count_out_of_scope() -> None:
    hidden = Measurement[int](name="shots", side=Side.THIS_MODEL, body=_three)
    hit = Roll[int](name="roll-to-hit", side=Side.THIS_MODEL, body=_d6, target=Scalar("t", 4))

    with pytest.raises(GraphError, match="runs shots times, which is not in scope"):
        Program.build("volley", _SIDES, (Group(name="attack", times=hidden, items=(hit,)),))


def test_two_steps_cannot_share_a_path() -> None:
    first = Measurement[int](name="shots", side=Side.THIS_MODEL, body=_three)
    second = Measurement[int](name="shots", side=Side.THIS_MODEL, body=_three)

    with pytest.raises(GraphError, match="volley/shots is declared twice"):
        Program.build("volley", _SIDES, (first, second))
