"""What every phase shares: its printed steps.

A phase is a value the game assembles, owning exactly the rules in
force it needs — no reference back to the game. Its actions are
methods, each a one-line delegation into the combat modules, never
logic of its own; ``steps`` is the phase's printed step sequence,
drift-guarded to the Stage vocabulary's declaration order, which the
engine walks.
"""

from dataclasses import dataclass
from typing import ClassVar

from avelorn.tow.schema.stage import Stage


@dataclass(frozen=True)
class Phase:
    """A phase of the turn: printed steps, and actions as thin delegates."""

    steps: ClassVar[tuple[Stage, ...]] = ()
