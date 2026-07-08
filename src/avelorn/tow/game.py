"""A game of The Old World in play: the rules in force, the turn's phases.

The Game owns what belongs to neither side — the chapter rules that
apply to every action of a phase (Firing at Long Range, Moving and
Shooting), resolved once at :meth:`Game.assemble`, the way a loadout
resolves a unit's printed names at fielding. It also owns the turn's
structure: the printed phase sequence, each phase bound to the game
with its printed steps and its actions.

Game owns the rules in force and the turn's structure — **never the
math**. Every action method is a one-line delegation into the combat
modules, injecting the game's rules; the underlying functions stay
importable directly, nothing is moved, only bound. The moment a Game
method grows a second line of logic, the god object has begun: move the
logic into a module and delegate.

Deliberately stateless: "walk the turn step by step" is an ordered
tuple, not a mutable cursor. Whose turn it is, casualties persisting
across phases — that is a Battle object *on top of* Game, if ever.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import ClassVar

from avelorn.core.registry import Registry
from avelorn.tow.combat.charge import ChargeResult, StandAndShoot, charge, stand_and_shoot
from avelorn.tow.combat.context import CombatContext, EngagementContext
from avelorn.tow.combat.contingent import Charge, Contingent
from avelorn.tow.combat.melee import CombatResult, FightResult, combat_result, fight
from avelorn.tow.combat.morale import BreakResult, PanicResult, break_test, make_panic_tests
from avelorn.tow.combat.shooting import ShootingResult, shoot_unit
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.stage import Stage
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon


@dataclass(frozen=True)
class Game:
    """A game in play: the rules in force, bound to the turn's phases.

    Assemble one from a rule registry (:meth:`assemble`); the chapter
    rules each phase has in force are resolved right there, eagerly —
    the game's own muster boundary. Walk the turn with :meth:`turn`, or
    address a phase directly (``game.shooting.volley(...)``); sequences
    that span phases (a charge: declared in Movement, fought in Combat)
    live on the game itself.
    """

    rules: Registry[Rule]
    in_play: Mapping[Phase, Mapping[str, Rule]]

    @classmethod
    def assemble(cls, rules: Registry[Rule]) -> "Game":
        """Assemble a game from the rules, resolving what each phase has in force.

        A chapter rule is in force when its category names the phase and
        it carries effects — recognised chapter text *without* effects is
        deliberately not in force and not reported, the one honesty
        trade-off the engine makes (noting it on every action of the
        phase would drown the notes that matter).

        Returns:
            The assembled game, chapter rules resolved per phase.
        """
        in_play = {
            phase: {
                rule.name: rule
                for rule in rules.values()
                if rule.category == phase and rule.effects
            }
            for phase in Phase
        }
        return cls(rules=rules, in_play=in_play)

    def turn(self) -> tuple["StrategyPhase", "MovementPhase", "ShootingPhase", "CombatPhase"]:
        """The turn as printed: the four phases, in order, bound to this game.

        Returns:
            The phase bindings, in the printed sequence.
        """
        return (self.strategy, self.movement, self.shooting, self.combat)

    @property
    def strategy(self) -> "StrategyPhase":
        """The Strategy phase, bound to this game."""
        return StrategyPhase(self)

    @property
    def movement(self) -> "MovementPhase":
        """The Movement phase, bound to this game."""
        return MovementPhase(self)

    @property
    def shooting(self) -> "ShootingPhase":
        """The Shooting phase, bound to this game."""
        return ShootingPhase(self)

    @property
    def combat(self) -> "CombatPhase":
        """The Combat phase, bound to this game."""
        return CombatPhase(self)

    def charge(
        self,
        charger: Contingent,
        target: Contingent,
        *,
        move: Charge,
        charger_weapon: Weapon,
        target_weapon: Weapon,
        reaction: StandAndShoot | None = None,
    ) -> ChargeResult:
        """Resolve a charge: declaration and reaction, then the fight it feeds.

        A charge spans phases — declared and reacted to in Movement,
        fought in Combat — so the game, owner of the turn, is what walks
        it across them.

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
            rules=self.rules,
        )


@dataclass(frozen=True)
class StrategyPhase:
    """The Strategy phase, bound to a game; none of its actions are modelled yet."""

    game: Game
    steps: ClassVar[tuple[Stage, ...]] = ()


@dataclass(frozen=True)
class MovementPhase:
    """The Movement phase, bound to a game: charge reactions resolve here."""

    game: Game
    steps: ClassVar[tuple[Stage, ...]] = ()

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
        return stand_and_shoot(shooter, target, weapon, rules=self.game.rules)


@dataclass(frozen=True)
class ShootingPhase:
    """The Shooting phase, bound to a game: its printed steps, its actions.

    ``steps`` is the printed shooting sequence; the binding's methods are
    the phase's actions, each a one-line delegation with the game's
    chapter rules in force.
    """

    game: Game
    # The printed shooting sequence. Declared here because the game owns
    # the turn's structure; a drift-guard test holds the order to the
    # Stage vocabulary's declaration order, which the engine walks.
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
            rules=self.game.rules,
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


@dataclass(frozen=True)
class CombatPhase:
    """The Combat phase, bound to a game: its steps, its round's actions."""

    game: Game
    # The rolls of the printed combat sequence. The phase's other printed
    # steps (choose combats, calculate combat result, break tests) join
    # Stage append-only when rule text demands them, as ever.
    steps: ClassVar[tuple[Stage, ...]] = (
        Stage.ROLL_TO_HIT,
        Stage.ROLL_TO_WOUND,
        Stage.MAKE_ARMOUR_SAVES,
        Stage.WARD_SAVES,
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
