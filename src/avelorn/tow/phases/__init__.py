"""The turn's phases, one module per printed phase.

Each module implements one phase: a value the game assembles, carrying
its printed steps, the rules in force it needs, and the phase's
actions — every action a one-line delegation into the combat modules,
never logic of its own. The turn's order is declared by the game
itself (:class:`avelorn.tow.game.TOWGame`); the schema's Phase
vocabulary names the phases for rule data.
"""

from avelorn.tow.phases.combat import CombatPhase
from avelorn.tow.phases.movement import MovementPhase
from avelorn.tow.phases.phase import Phase
from avelorn.tow.phases.shooting import ShootingPhase
from avelorn.tow.phases.strategy import StrategyPhase

__all__ = ["CombatPhase", "MovementPhase", "Phase", "ShootingPhase", "StrategyPhase"]
