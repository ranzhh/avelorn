"""The turn's phases, one module per printed phase.

Each module implements one phase: a value the game assembles, holding the
program its actions run on, loaded with the corpus rules. Every action is a
delegation to the graph (:mod:`avelorn.tow.volley`, :mod:`avelorn.tow.round`),
never logic of its own (the shared shape is :class:`avelorn.core.game.Phase`).
The turn's order is declared by the game itself
(:class:`avelorn.tow.game.TOWGame`); the schema's Phase vocabulary names the
phases for rule data.
"""

from avelorn.tow.phases.combat import CombatPhase
from avelorn.tow.phases.movement import MovementPhase
from avelorn.tow.phases.shooting import ShootingPhase
from avelorn.tow.phases.strategy import StrategyPhase

__all__ = ["CombatPhase", "MovementPhase", "ShootingPhase", "StrategyPhase"]
