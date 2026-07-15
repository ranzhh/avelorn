"""The Shooting phase: the volley and its panic step."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from avelorn.core.game import Phase
from avelorn.tow.combat.attack import ArmourSave, Roll, RollToHitShooting, RollToWound, WardSave
from avelorn.tow.combat.contingent import Contingent
from avelorn.tow.combat.morale import PanicResult, PanicTest, make_panic_tests
from avelorn.tow.combat.shooting import ShootingResult, shoot_unit
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.weapon import Weapon


@dataclass(frozen=True)
class ShootingPhase(Phase):
    """The Shooting phase: its printed steps, its actions.

    ``in_play`` are the chapter's rules in force — every volley
    resolves under them.
    """

    in_play: Mapping[str, Rule]

    # The printed shooting sequence: every step knows what it rolls —
    # attack dice with their semantics (this Roll to Hit confirms 7+),
    # then the unit-wide 2D6 panic test. The declaration: drift guards
    # hold the attack factory and the Stage order to it.
    steps: ClassVar[tuple[type[Roll], ...]] = (
        RollToHitShooting,
        RollToWound,
        ArmourSave,
        WardSave,
        PanicTest,
    )

    def volley(
        self,
        attacker: Contingent,
        defender: Contingent,
        weapon: Weapon,
        *,
        distance: int | None = None,
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
            distance=distance,
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
