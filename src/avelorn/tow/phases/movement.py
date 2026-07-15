"""The Movement phase: charges are declared, reacted to, and moved here."""

from collections.abc import Mapping
from dataclasses import dataclass

from avelorn.core.game import Phase
from avelorn.tow.combat.charge import HOLD, ChargeReaction, ChargeResult, charge, stand_and_shoot
from avelorn.tow.combat.shooting import ShootingResult
from avelorn.tow.contingent import Charge, Contingent
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.weapon import Weapon


@dataclass(frozen=True)
class MovementPhase(Phase):
    """The Movement phase: the charge, and the reactions that answer it.

    ``shooting_in_play`` are the *shooting* chapter's rules in force —
    a Stand & Shoot reaction volley resolves under them. The movement
    chapter's own rules have no path into the math yet; when one gains
    effects, this phase grows its own ``in_play`` beside this field.
    """

    shooting_in_play: Mapping[str, Rule]

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

        The Stand & Shoot reaction volley resolves under the shooting
        chapter's rules. The fight the charge feeds does not yet see the
        combat chapter's rules: the charge threads only the shooting rules
        it holds, and wiring the combat rules through waits until a combat
        chapter rule has effects to honour.

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
            phase_rules=self.shooting_in_play,
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
        return stand_and_shoot(shooter, target, weapon, phase_rules=self.shooting_in_play)
