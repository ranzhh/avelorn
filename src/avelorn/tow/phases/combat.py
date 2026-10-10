"""The Combat phase: each round of a combat, fought on the round program."""

from dataclasses import dataclass
from typing import overload

from avelorn.core.game import Phase
from avelorn.tow.contingent import Contingent
from avelorn.tow.phases.movement import Engagement
from avelorn.tow.programs import Loaded
from avelorn.tow.round import Fight, fight_round


@dataclass(frozen=True)
class CombatPhase(Phase):
    """The Combat phase: its round's actions.

    ``program`` is the round program, loaded with the corpus rules; every
    round of combat runs on it.
    """

    program: Loaded

    @overload
    def fight(self, combat: Engagement, /) -> Fight: ...

    @overload
    def fight(self, combat: Contingent, opponent: Contingent, /) -> Fight: ...

    def fight(
        self,
        combat: Engagement | Contingent,
        opponent: Contingent | None = None,
        /,
    ) -> Fight:
        """One round of a combat, each side fighting with the weapon it has in hand.

        ``combat`` is either an :class:`~avelorn.tow.phases.movement.Engagement`
        -- a charge-formed combat, in its first round until the turn ends, the
        charger thinned by any Stand & Shoot -- or two contingents in base
        contact, fought as a first round when either carries a charge.

        Returns:
            The round's lane in which every rule the players may decline is taken.

        Raises:
            ValueError: a lone contingent with no opponent and no engagement.
        """
        if isinstance(combat, Engagement):
            return fight_round(
                self.program,
                combat.a,
                combat.b,
                first_round=combat.first_round,
                stood=combat.reaction,
            )
        if opponent is None:
            raise ValueError("fighting two contingents needs both; pass an Engagement otherwise")
        charged = combat.movement.charge is not None or opponent.movement.charge is not None
        return fight_round(self.program, combat, opponent, first_round=charged)
