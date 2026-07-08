"""The turn-structured game skeleton."""

from typing import ClassVar

from avelorn.core.game import Game


class _Checkers(Game):
    # A minimal concrete game: two phases, declared in play order.
    phase_sequence: ClassVar[tuple[str, ...]] = ("red", "black")
    red = "red moves"
    black = "black moves"


def test_turn_walks_the_declared_phase_sequence() -> None:
    """turn() yields the declared phase attributes, in declared order."""
    assert _Checkers().turn() == ("red moves", "black moves")


def test_a_game_declares_no_phases_by_default() -> None:
    """The skeleton itself has no turn; a concrete game must declare one."""
    assert Game().turn() == ()
