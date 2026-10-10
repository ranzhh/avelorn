"""The Shooting phase: each volley, fired on the volley program."""

from dataclasses import dataclass

from avelorn.core.game import Phase
from avelorn.tow.contingent import Contingent
from avelorn.tow.programs import Loaded
from avelorn.tow.volley import Volley, fire


@dataclass(frozen=True)
class ShootingPhase(Phase):
    """The Shooting phase: its volleys.

    ``program`` is the volley program, loaded with the corpus rules; every
    volley runs on it.
    """

    program: Loaded

    def volley(
        self,
        shooter: Contingent,
        target: Contingent,
        *,
        distance: int,
        battle_strength: int | None = None,
    ) -> Volley:
        """One unit shoots another with the weapon in hand, and the target tests its nerve.

        Returns:
            The volley's lane in which every rule the players may decline is taken.
        """
        return fire(
            self.program,
            shooter,
            target,
            distance=distance,
            battle_strength=battle_strength,
        )
