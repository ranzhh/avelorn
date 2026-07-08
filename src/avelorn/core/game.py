"""The shared skeleton of turn-structured games.

At this altitude, a game is an ordered sequence of phases, each phase a
sequence of steps carrying actions. This module owns that shape and
nothing else — no rules, no data, no math. A concrete game (e.g.
:class:`avelorn.tow.game.TOWGame`) declares its printed phase sequence
and binds each phase to its actions; this base only walks it.
"""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Phase:
    """A phase of a game's turn: printed steps, and actions as thin delegates.

    A phase is a value the game assembles, owning exactly what it
    needs — no reference back to the game. ``steps`` is the phase's
    printed step sequence in the concrete game's own step vocabulary;
    its actions are methods, each a thin delegation into the game's
    logic modules, never logic of their own.
    """

    steps: ClassVar[tuple[str, ...]] = ()


class Game:
    """A turn-structured game: declared phases, walked in printed order.

    A subclass declares ``phase_sequence`` — the attribute names of its
    :class:`Phase` values, in the order its rulebook prints them — and
    :meth:`turn` walks it.
    """

    phase_sequence: ClassVar[tuple[str, ...]] = ()

    def turn(self) -> tuple[Phase, ...]:
        """The game's phases in printed order, each bound to this game.

        Returns:
            The phase bindings, in declared sequence.
        """
        return tuple(getattr(self, name) for name in self.phase_sequence)
