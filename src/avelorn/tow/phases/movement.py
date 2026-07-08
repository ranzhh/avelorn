"""The Movement phase: charge reactions resolve here."""

from avelorn.tow.combat.charge import stand_and_shoot
from avelorn.tow.combat.contingent import Contingent
from avelorn.tow.combat.shooting import ShootingResult
from avelorn.tow.phases.binding import PhaseBinding
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.weapon import Weapon


class MovementPhase(PhaseBinding):
    """The Movement phase, bound to a game: charge reactions resolve here."""

    def stand_and_shoot(
        self,
        shooter: Contingent,
        target: Contingent,
        weapon: Weapon,
    ) -> ShootingResult:
        """The Stand & Shoot charge reaction: one volley at the closing chargers.

        Returns:
            The volley's outcome — chargers felled before they strike.
        """
        return stand_and_shoot(
            shooter, target, weapon, phase_rules=self.game.in_play[Phase.SHOOTING]
        )
