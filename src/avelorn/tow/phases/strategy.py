"""The Strategy phase."""

from dataclasses import dataclass

from avelorn.core.game import Phase


@dataclass(frozen=True)
class StrategyPhase(Phase):
    """The Strategy phase; none of its actions are modelled yet."""
