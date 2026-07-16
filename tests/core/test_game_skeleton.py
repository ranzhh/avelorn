"""The turn-structured game skeleton."""

from dataclasses import dataclass
from typing import ClassVar

from avelorn.core.game import Game, Phase


@dataclass(frozen=True)
class _Move(Phase):
    steps: ClassVar[tuple[str, ...]] = ("move", "capture")


class _Checkers(Game):
    # A minimal concrete game: two phases, declared in play order.
    phase_sequence: ClassVar[tuple[str, ...]] = ("red", "black")
    red = _Move()
    black = _Move()


def test_phases_walk_the_declared_phase_sequence() -> None:
    """phases() yields the declared phase values, in declared order."""
    game = _Checkers()
    assert game.phases() == (game.red, game.black)
    assert game.phases()[0].steps == ("move", "capture")


def test_a_game_declares_no_phases_by_default() -> None:
    """The skeleton itself has no phases; a concrete game must declare them."""
    assert Game().phases() == ()
    assert Phase().steps == ()
