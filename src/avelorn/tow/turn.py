"""Walking a turn: its phases in order, and the combats it forms.

A :class:`Turn` is a scaffold over the game's phase values, not new resolution
logic. It walks the printed phase sequence — each phase entered through a
context manager that yields the phase to act through and enforces the order (a
phase may be skipped, but never revisited or taken out of sequence) — and
tracks the engagements its charges form, so the Combat phase fights the combats
that exist. It holds no sides: the units act in the calls, at whatever number
the question needs.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from avelorn.tow.contingent import Charge, Contingent
from avelorn.tow.phases.combat import CombatPhase
from avelorn.tow.phases.movement import Engagement, MovementPhase
from avelorn.tow.phases.shooting import ShootingPhase
from avelorn.tow.phases.strategy import StrategyPhase
from avelorn.tow.schema.phase import Phase

_ORDER: dict[Phase, int] = {phase: order for order, phase in enumerate(Phase)}


@dataclass
class _Movement:
    """The Movement phase within a turn: a charge's engagement joins the turn.

    Thin over :class:`~avelorn.tow.phases.movement.MovementPhase` — only
    :meth:`charge` differs, registering the engagement it forms on the turn so
    the Combat phase can fight it.
    """

    _phase: MovementPhase
    _turn: "Turn"

    def charge(self, charger: Contingent, target: Contingent, move: Charge) -> Engagement:
        """Declare a charge; its engagement joins the turn's combats.

        Returns:
            The engagement the charge formed — react on it, and the Combat
            phase fights it.
        """
        engagement = self._phase.charge(charger, target, move)
        self._turn.engagements.append(engagement)
        return engagement


@dataclass
class Turn:
    """A turn in progress: its phases walked in order, its combats tracked.

    Made by :meth:`~avelorn.tow.game.TOWGame.turn`. Enter each phase through
    its context manager (:meth:`strategy`, :meth:`movement`, :meth:`shooting`,
    :meth:`combat`) to act through it; the order is enforced — a phase may be
    skipped, but never revisited or taken out of sequence. Charges made in the
    Movement phase leave their engagements in :attr:`engagements`, which the
    Combat phase fights.
    """

    _strategy: StrategyPhase
    _movement: MovementPhase
    _shooting: ShootingPhase
    _combat: CombatPhase
    # The combats formed this turn (by charges), in the order declared.
    engagements: list[Engagement] = field(default_factory=list)
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
    def movement(self) -> Iterator[_Movement]:
        """Enter the Movement phase: declare charges, which form engagements.

        Yields:
            The Movement phase, whose ``charge`` registers each engagement on
            the turn.
        """
        self._enter(Phase.MOVEMENT)
        yield _Movement(self._movement, self)

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
        """Enter the Combat phase: fight the turn's engagements.

        Yields:
            The Combat phase; fight each of the turn's :attr:`engagements`.
        """
        self._enter(Phase.COMBAT)
        yield self._combat
