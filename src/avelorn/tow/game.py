"""A game of The Old World in play: the rules in force, the turn's phases.

The Game owns what belongs to neither side — the chapter rules that
apply to every action of a phase (Firing at Long Range, Moving and
Shooting) — and the turn's structure: the printed phase sequence, each
phase in its own module under :mod:`avelorn.tow.phases`.

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
from avelorn.tow.contingent import Contingent
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

    Assemble one from the loaded corpus (:meth:`assemble`, or
    :meth:`load_data` straight from data/); the chapter rules each
    phase has in force are resolved right there, eagerly — the game's
    own muster boundary — and each phase is assembled as a value owning
    exactly what it needs. Walk the turn with ``turn()``, or address a
    phase directly (``game.shooting.volley(...)``,
    ``game.movement.charge(...)``).
    """

    # The printed corpus, as loaded: the game's registries, kept for the
    # muster boundary (field/deploy), where printed names stop being strings.
    units: Registry[Unit]
    weapons: Registry[Weapon]
    armoury: Registry[Armour]
    rules: Registry[Rule]
    # The chapter rules each phase has in force, resolved at assembly.
    # Consumed by the shooting seam (volleys, and the reaction volley
    # Movement borrows) and the combat seam (every round, gated by each
    # side's conditions); a chapter rule gaining effects is a data change
    # honoured by whichever phase names it.
    in_play: Mapping[Phase, Mapping[str, Rule]]
    # The turn's phases, assembled as values — each owns exactly the
    # rules in force it needs; none holds a reference back to the game.
    strategy: StrategyPhase
    movement: MovementPhase
    shooting: ShootingPhase
    combat: CombatPhase

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
            strategy=StrategyPhase(),
            movement=MovementPhase(shooting_in_play=in_play[Phase.SHOOTING]),
            shooting=ShootingPhase(in_play=in_play[Phase.SHOOTING]),
            combat=CombatPhase(in_play=in_play[Phase.COMBAT]),
        )

    @classmethod
    def load_data(cls) -> "TOWGame":
        """Load the printed corpus from data/ and assemble the game in play.

        The one-call entry point: the repository is an implementation
        detail here — the game holds the data from then on. To assemble
        from a corpus you already loaded (or doctored), use
        :meth:`assemble`.

        Returns:
            The assembled game.
        """
        return cls.assemble(TOWRepository())

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
