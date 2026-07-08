"""The shared skeleton of turn-structured games.

At this altitude, a game is an ordered sequence of phases, each phase a
sequence of steps carrying actions. This module owns that shape and
nothing else — no rules, no data, no math. A concrete game (e.g.
:class:`avelorn.tow.game.TOWGame`) declares its printed phase sequence
and binds each phase to its actions; this base only walks it.
"""

from typing import ClassVar


class Game:
    """A turn-structured game: declared phases, walked in printed order.

    A subclass declares ``phase_sequence`` — the attribute names of its
    phase bindings, in the order its rulebook prints them — and
    :meth:`turn` walks it. What a binding is stays the subclass's
    concern; by convention it carries the phase's printed ``steps`` and
    its actions, each a thin delegation into the game's logic modules.
    """

    phase_sequence: ClassVar[tuple[str, ...]] = ()

    def turn(self) -> tuple[object, ...]:
        """The game's phases in printed order, each bound to this game.

        Returns:
            The phase bindings, in declared sequence.
        """
        return tuple(getattr(self, name) for name in self.phase_sequence)
