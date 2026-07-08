"""The Movement phase: charges are declared, reacted to, and moved here."""

from collections.abc import Mapping
from dataclasses import dataclass

from avelorn.tow.combat.charge import HOLD, ChargeReaction, ChargeResult, charge, stand_and_shoot
from avelorn.tow.combat.contingent import Charge, Contingent
from avelorn.tow.combat.shooting import ShootingResult
from avelorn.tow.phases.phase import Phase
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.weapon import Weapon


@dataclass(frozen=True)
class MovementPhase(Phase):
    """The Movement phase: the charge, and the reactions that answer it.

    ``in_play`` are the shooting chapter's rules in force — a Stand &
    Shoot reaction volley resolves under them.
    """

    in_play: Mapping[str, Rule]

    def charge(
        self,
        charger: Contingent,
        target: Contingent,
        *,
        move: Charge,
        charger_weapon: Weapon,
        target_weapon: Weapon,
        reaction: ChargeReaction = HOLD,
    ) -> ChargeResult:
        """A charge is declared, answered, and driven home.

        The fight the charge feeds resolves by the Combat phase's rules,
        composed here so the sequence plays as the rulebook plays it.

        Returns:
            The composed outcome: the reaction volley, if any, and the fight.
        """
        return charge(
            charger,
            target,
            move=move,
            charger_weapon=charger_weapon,
            target_weapon=target_weapon,
            reaction=reaction,
            phase_rules=self.in_play,
        )

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
        return stand_and_shoot(shooter, target, weapon, phase_rules=self.in_play)
