"""The Shooting phase: the volley and its panic step."""

from typing import ClassVar

from avelorn.tow.combat.context import EngagementContext
from avelorn.tow.combat.contingent import Contingent
from avelorn.tow.combat.morale import PanicResult, make_panic_tests
from avelorn.tow.combat.shooting import ShootingResult, shoot_unit
from avelorn.tow.phases.binding import PhaseBinding
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.stage import Stage
from avelorn.tow.schema.weapon import Weapon


class ShootingPhase(PhaseBinding):
    """The Shooting phase, bound to a game: its printed steps, its actions."""

    # The printed shooting sequence.
    steps: ClassVar[tuple[Stage, ...]] = (
        Stage.ROLL_TO_HIT,
        Stage.ROLL_TO_WOUND,
        Stage.MAKE_ARMOUR_SAVES,
        Stage.WARD_SAVES,
        Stage.MAKE_PANIC_TESTS,
    )

    def volley(
        self,
        attacker: Contingent,
        defender: Contingent,
        weapon: Weapon,
        *,
        context: EngagementContext | None = None,
        hit_modifier: int = 0,
    ) -> ShootingResult:
        """One unit shoots another, under the phase's rules in force.

        Returns:
            The shooting outcome.
        """
        return shoot_unit(
            attacker,
            defender,
            weapon,
            phase_rules=self.game.in_play[Phase.SHOOTING],
            context=context,
            hit_modifier=hit_modifier,
        )

    def make_panic_tests(
        self,
        result: ShootingResult,
        defender: Contingent,
        *,
        battle_strength: int | None = None,
    ) -> PanicResult:
        """The panic step for one volley's casualties.

        Returns:
            The panic outcome distribution.
        """
        return make_panic_tests(result, defender, battle_strength=battle_strength)
