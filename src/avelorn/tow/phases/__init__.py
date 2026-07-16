"""The turn's phases, one module per printed phase.

Each module implements one phase: a value the game assembles, carrying
its printed steps, the rules in force it needs, and the phase's
actions — every action a one-line delegation into its own module's
resolution functions, never logic of its own (the shared shape is
:class:`avelorn.core.game.Phase`). The shared, phase-agnostic mathematics
those functions build on lives in :mod:`avelorn.tow.engine`. The turn's
order is declared by the game
itself (:class:`avelorn.tow.game.TOWGame`); the schema's Phase
vocabulary names the phases for rule data.
"""

from avelorn.tow.phases.combat import CombatPhase
from avelorn.tow.phases.movement import MovementPhase
from avelorn.tow.phases.shooting import ShootingPhase
from avelorn.tow.phases.strategy import StrategyPhase

__all__ = ["CombatPhase", "MovementPhase", "ShootingPhase", "StrategyPhase"]
