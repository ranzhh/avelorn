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
from avelorn.tow.data import TOWRepository
from avelorn.tow.muster import Complement
from avelorn.tow.phases import CombatPhase, MovementPhase, ShootingPhase, StrategyPhase
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon


@dataclass(frozen=True)
class TOWGame(Game):
    """A game of The Old World in play: rules in force, bound to the turn.

    Assemble one from the loaded corpus (:meth:`assemble`); the chapter
    rules each phase has in force are resolved right there, eagerly —
    the game's own muster boundary. Walk the turn with ``turn()``, or
    address a phase directly (``game.shooting.volley(...)``); sequences
    that span phases (a charge: declared in Movement, fought in Combat)
    live on the game itself.
    """

    # The printed corpus, as loaded: the game's registries, kept for the
    # muster boundary (field/deploy), where printed names stop being strings.
    units: Registry[Unit]
    weapons: Registry[Weapon]
    armoury: Registry[Armour]
    rules: Registry[Rule]
    # The chapter rules each phase has in force, resolved at assembly.
    in_play: Mapping[Phase, Mapping[str, Rule]]

    # The printed turn sequence, derived from the Phase vocabulary: each
    # member names the binding property below.
    phase_sequence: ClassVar[tuple[str, ...]] = tuple(phase.name.lower() for phase in Phase)

    @classmethod
    def assemble(cls, repository: TOWRepository) -> "TOWGame":
        """Assemble a game from the loaded corpus, resolving each phase's rules in force.

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
                for rule in repository.rules.values()
                if rule.category == phase and rule.effects
            }
            for phase in Phase
        }
        return cls(
            units=repository.units,
            weapons=repository.weapons,
            armoury=repository.armoury,
            rules=repository.rules,
            in_play=in_play,
        )

    def field(self, unit: Unit, models: int) -> Contingent:
        """Field a bare datasheet at its printed, optionless loadout.

        Returns:
            The fielded contingent, loadout resolved with the game's registries.
        """
        return Contingent.field(
            unit, models, weapons=self.weapons, armoury=self.armoury, rules=self.rules
        )

    def deploy(self, complement: Complement) -> Contingent:
        """Field a mustered list entry, resolving its chosen loadout.

        Returns:
            The fielded contingent, loadout resolved with the game's registries.
        """
        return Contingent.deploy(
            complement, weapons=self.weapons, armoury=self.armoury, rules=self.rules
        )

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
