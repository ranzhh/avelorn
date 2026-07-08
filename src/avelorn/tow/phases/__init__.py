"""The turn's phases, one module per printed phase.

Each module implements its phase's binding: the phase bound to a game,
carrying the printed steps and the phase's actions — every action a
one-line delegation into the combat modules with the game's rules
injected, never logic of its own. The turn's order is declared by the
game itself (:class:`avelorn.tow.game.TOWGame`); the schema's
:class:`~avelorn.tow.schema.phase.Phase` vocabulary names the phases
for rule data.
"""

from avelorn.tow.phases.combat import CombatPhase
from avelorn.tow.phases.movement import MovementPhase
from avelorn.tow.phases.shooting import ShootingPhase
from avelorn.tow.phases.strategy import StrategyPhase

__all__ = ["CombatPhase", "MovementPhase", "ShootingPhase", "StrategyPhase"]
