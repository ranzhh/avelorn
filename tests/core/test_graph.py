from fractions import Fraction

import pytest

from avelorn.core.distribution import Distribution
from avelorn.core.graph import (
    Consequence,
    GraphError,
    Group,
    Measurement,
    Program,
    Roll,
    Scalar,
    Side,
)

_SIXTH = Fraction(1, 6)
_SIDES = {Side.THIS_MODEL: "the archers", Side.THE_ENEMY: "the spearmen"}


def _d6() -> Distribution[int]:
    return Distribution({face: _SIXTH for face in range(1, 7)})


def _three() -> int:
    return 3


def _toll(face: int) -> int:
    return face


def test_a_path_is_the_step_place_in_the_block_tree() -> None:
    shots = Measurement[int](name="shots", side=Side.THIS_MODEL, body=_three)
    hit = Roll[int](name="roll-to-hit", side=Side.THIS_MODEL, body=_d6, target=Scalar("t", 4))
    attack = Group(name="attack", times=shots, items=(hit,))
    program = Program.build("volley", _SIDES, (shots, attack))

    assert program.paths[shots] == "volley/shots"
    assert program.paths[attack] == "volley/attack"
    assert program.paths[hit] == "volley/attack/roll-to-hit"
    assert program.steps == (shots, hit)
    assert program.blocks == (attack,)


def test_a_step_reads_an_enclosing_block() -> None:
    strength = Measurement[int](name="strength", side=Side.THIS_MODEL, body=_three)
    wound = Roll[int](
        name="roll-to-wound",
        side=Side.THIS_MODEL,
        reads=(strength,),
        body=_d6,
        target=Scalar("t", 4),
    )
    program = Program.build(
        "volley",
        _SIDES,
        (strength, Group(name="attack", times=strength, items=(wound,))),
    )

    assert program.paths[wound] == "volley/attack/roll-to-wound"


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
