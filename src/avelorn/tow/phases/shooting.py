"""The Shooting phase: the volley and its panic step."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from avelorn.tow.combat.context import EngagementContext
from avelorn.tow.combat.contingent import Contingent
from avelorn.tow.combat.morale import PanicResult, make_panic_tests
from avelorn.tow.combat.shooting import ShootingResult, shoot_unit
from avelorn.tow.phases.phase import Phase
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.stage import Stage
from avelorn.tow.schema.weapon import Weapon


@dataclass(frozen=True)
class ShootingPhase(Phase):
    """The Shooting phase: its printed steps, its actions.

    ``in_play`` are the chapter's rules in force — every volley
    resolves under them.
    """

    in_play: Mapping[str, Rule]

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
            phase_rules=self.in_play,
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
