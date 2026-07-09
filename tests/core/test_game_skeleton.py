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


def test_turn_walks_the_declared_phase_sequence() -> None:
    """turn() yields the declared phase values, in declared order."""
    game = _Checkers()
    assert game.turn() == (game.red, game.black)
    assert game.turn()[0].steps == ("move", "capture")


def test_a_game_declares_no_phases_by_default() -> None:
    """The skeleton itself has no turn; a concrete game must declare one."""
    assert Game().turn() == ()
    assert Phase().steps == ()
