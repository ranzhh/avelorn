"""A game of The Old World in play: the rules in force, the turn's phases.

The Game owns what belongs to neither side — the chapter rules that
apply to every action of a phase (Firing at Long Range, Moving and
Shooting), resolved once at :meth:`TOWGame.assemble`, the way a loadout
resolves a unit's printed names at fielding. It also owns the turn's
structure: the printed phase sequence, each phase bound to the game —
one module per phase, under :mod:`avelorn.tow.phases`.

The game owns the rules in force and the turn's structure — **never
the math**. Every action method is a one-line delegation into the
combat modules, injecting the game's rules; the underlying functions
stay importable directly, nothing is moved, only bound. The moment a
game method grows a second line of logic, the god object has begun:
move the logic into a module and delegate.

Deliberately stateless: "walk the turn step by step" is an ordered
tuple, not a mutable cursor. Whose turn it is, casualties persisting
across phases — that is a Battle object *on top of* the game, if ever.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from avelorn.core.game import Game
from avelorn.core.registry import Registry
from avelorn.tow.combat.charge import ChargeResult, StandAndShoot, charge
from avelorn.tow.combat.contingent import Charge, Contingent
from avelorn.tow.phases import CombatPhase, MovementPhase, ShootingPhase, StrategyPhase
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.weapon import Weapon


@dataclass(frozen=True)
class TOWGame(Game):
    """A game of The Old World in play: rules in force, bound to the turn.

    Assemble one from a rule registry (:meth:`assemble`); the chapter
    rules each phase has in force are resolved right there, eagerly —
    the game's own muster boundary. Walk the turn with ``turn()``, or
    address a phase directly (``game.shooting.volley(...)``); sequences
    that span phases (a charge: declared in Movement, fought in Combat)
    live on the game itself.
    """

    in_play: Mapping[Phase, Mapping[str, Rule]]

    # The printed turn sequence, derived from the Phase vocabulary: each
    # member names the binding property below.
    phase_sequence: ClassVar[tuple[str, ...]] = tuple(phase.name.lower() for phase in Phase)

    @classmethod
    def assemble(cls, rules: Registry[Rule]) -> "TOWGame":
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
        return cls(in_play=in_play)

    @property
    def strategy(self) -> StrategyPhase:
        """The Strategy phase, bound to this game."""
        return StrategyPhase(self)

    @property
    def movement(self) -> MovementPhase:
        """The Movement phase, bound to this game."""
        return MovementPhase(self)

    @property
    def shooting(self) -> ShootingPhase:
        """The Shooting phase, bound to this game."""
        return ShootingPhase(self)

    @property
    def combat(self) -> CombatPhase:
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
            phase_rules=self.in_play[Phase.SHOOTING],
        )
