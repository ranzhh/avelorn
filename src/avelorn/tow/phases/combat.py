"""The Combat phase: the round, its result, the Break test."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from avelorn.core.game import Phase
from avelorn.tow.combat.attack import ArmourSave, Roll, RollToHitCombat, RollToWound, WardSave
from avelorn.tow.combat.context import CombatContext
from avelorn.tow.combat.contingent import Contingent
from avelorn.tow.combat.melee import CombatResult, FightResult, combat_result, fight
from avelorn.tow.combat.morale import BreakResult, break_test
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon


@dataclass(frozen=True)
class CombatPhase(Phase):
    """The Combat phase: its steps, its round's actions.

    ``in_play`` are the chapter's rules in force — every round of combat
    resolves under them, gated by each side's engagement conditions. No
    combat chapter rule carries effects in the data today, so the mapping
    is empty in practice; the path is here, so a rule gaining effects is a
    data change, honoured like its shooting sibling, not new code.
    """

    in_play: Mapping[str, Rule]

    # The printed combat sequence's modelled steps: every step knows
    # what it rolls — this Roll to Hit never confirms (a natural 6
    # always hits). The phase's other printed steps (choose combats,
    # calculate combat result, break tests) join when modelled, each as
    # a step that knows how it resolves.
    steps: ClassVar[tuple[type[Roll], ...]] = (
        RollToHitCombat,
        RollToWound,
        ArmourSave,
        WardSave,
    )

    def fight(
        self,
        a: Contingent,
        b: Contingent,
        *,
        a_weapon: Weapon,
        b_weapon: Weapon,
        a_prior_losses: Sequence[float] | None = None,
        b_prior_losses: Sequence[float] | None = None,
        context: CombatContext | None = None,
    ) -> FightResult:
        """One round of close combat between two units.

        Returns:
            The round's joint casualty distribution.
        """
        return fight(
            a,
            b,
            a_weapon=a_weapon,
            b_weapon=b_weapon,
            a_prior_losses=a_prior_losses,
            b_prior_losses=b_prior_losses,
            context=context,
            phase_rules=self.in_play,
        )

    def result(self, fought: FightResult) -> CombatResult:
        """Score a fought round and name the winner.

        Returns:
            The win/draw/loss probabilities and signed margin.
        """
        return combat_result(fought)

    def break_test(self, scored: CombatResult, a: Unit, b: Unit) -> BreakResult:
        """The Break test for a scored round, for each side.

        Returns:
            Each side's break outcome distribution.
        """
        return break_test(scored, a, b)
