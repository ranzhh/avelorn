"""What every phase binding shares: a game, and printed steps.

TOW-side for now: a core-generic binding could not name
:class:`~avelorn.tow.schema.stage.Stage` or the TOW game, and every
subclass would re-declare both for typing. If a second game system
joins, this generalizes into :mod:`avelorn.core.game` beside the Game
skeleton.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from avelorn.tow.schema.stage import Stage

if TYPE_CHECKING:
    from avelorn.tow.game import TOWGame


@dataclass(frozen=True)
class PhaseBinding:
    """A phase of the turn, bound to a game of The Old World.

    ``steps`` is the phase's printed step sequence, drift-guarded to the
    Stage vocabulary's declaration order, which the engine walks. A
    phase's actions are methods on its binding — each a one-line
    delegation into the combat modules with the game's rules injected,
    never logic of its own.
    """

    game: "TOWGame"
    steps: ClassVar[tuple[Stage, ...]] = ()
