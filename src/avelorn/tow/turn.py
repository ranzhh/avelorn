"""Walking a turn: its phases, entered in the printed order.

A :class:`Turn` is a scaffold over the game's phase values, not new resolution
logic. It walks the printed phase sequence — each phase entered through a
context manager that yields the phase to act through and enforces the order (a
phase may be skipped, but never revisited or taken out of sequence). It holds
no sides and no state beyond how far the walk has reached: the units act in the
phase calls, and a charge's :class:`~avelorn.tow.phases.movement.Engagement` is
returned to the caller to carry into the Combat phase.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from avelorn.tow.phases.combat import CombatPhase
from avelorn.tow.phases.movement import MovementPhase
from avelorn.tow.phases.shooting import ShootingPhase
from avelorn.tow.phases.strategy import StrategyPhase
from avelorn.tow.schema.phase import Phase

_ORDER: dict[Phase, int] = {phase: order for order, phase in enumerate(Phase)}


@dataclass
class Turn:
    """A turn in progress: its phases entered in the printed order.

    Made by :meth:`~avelorn.tow.game.TOWGame.turn`. Enter each phase through
    its context manager (:meth:`strategy`, :meth:`movement`, :meth:`shooting`,
    :meth:`combat`) to act through the phase it yields; the order is enforced —
    a phase may be skipped, but never revisited or taken out of sequence. A
    charge in the Movement phase returns its engagement; hold it and fight it
    in the Combat phase.
    """

    _strategy: StrategyPhase
    _movement: MovementPhase
    _shooting: ShootingPhase
    _combat: CombatPhase
    # The order of the furthest phase entered; phases only move forward.
    _reached: int = -1

    def _enter(self, phase: Phase) -> None:
        # Advance the phase cursor, refusing a step back or a repeat.
        order = _ORDER[phase]
        if order <= self._reached:
            reached = next(name for name, at in _ORDER.items() if at == self._reached)
            raise ValueError(f"{phase.value} cannot be entered after {reached.value}")
        self._reached = order

    @contextmanager
    def strategy(self) -> Iterator[StrategyPhase]:
        """Enter the Strategy phase (nothing in it is modelled yet).

        Yields:
            The Strategy phase.
        """
        self._enter(Phase.STRATEGY)
        yield self._strategy

    @contextmanager
    def movement(self) -> Iterator[MovementPhase]:
        """Enter the Movement phase: declare charges, each forming an engagement.

        Yields:
            The Movement phase; its ``charge`` returns the engagement to fight.
        """
        self._enter(Phase.MOVEMENT)
        yield self._movement

    @contextmanager
    def shooting(self) -> Iterator[ShootingPhase]:
        """Enter the Shooting phase: resolve volleys.

        Yields:
            The Shooting phase.
        """
        self._enter(Phase.SHOOTING)
        yield self._shooting

    @contextmanager
    def combat(self) -> Iterator[CombatPhase]:
        """Enter the Combat phase: fight the engagements the charges formed.

        Yields:
            The Combat phase.
        """
        self._enter(Phase.COMBAT)
        yield self._combat
