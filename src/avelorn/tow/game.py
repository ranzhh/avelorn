"""A game of The Old World in play: the corpus, the turn's phases.

The Game owns what belongs to neither side -- the printed corpus -- and
the turn's structure: the printed phase sequence, each phase in its own
module under :mod:`avelorn.tow.phases`, running on a program loaded with
the corpus rules.

The game owns the corpus and the turn's structure -- **never the math**.
Every action method is a one-line delegation into the phase modules; the
underlying functions stay importable directly, nothing is moved, only
bound. The moment a game method grows a second line of logic, the god
object has begun: move the logic into a module and delegate.

Deliberately stateless: "walk the turn step by step" is an ordered
tuple, not a mutable cursor. Whose turn it is, casualties persisting
across phases — that is a Battle object *on top of* the game, if ever.
"""

from dataclasses import dataclass
from typing import ClassVar

from avelorn.core.game import Game
from avelorn.core.registry import Registry
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.muster import Complement
from avelorn.tow.phases import CombatPhase, MovementPhase, ShootingPhase, StrategyPhase
from avelorn.tow.programs import CHARGE, ROUND, STAND_AND_SHOOT, VOLLEY, load_program
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon
from avelorn.tow.turn import Turn


@dataclass(frozen=True)
class TOWGame(Game):
    """A game of The Old World in play: the corpus, bound to the turn.

    Assemble one from the loaded corpus (:meth:`assemble`, or
    :meth:`load_data` straight from data/); each phase is assembled as a
    value owning its program, loaded with the corpus rules. Walk the turn
    with ``turn()``, or address a phase directly
    (``game.shooting.volley(...)``, ``game.movement.charge(...)``).
    """

    # The printed corpus this game was assembled from: its single source of
    # data. The muster boundary (field/deploy) resolves printed names against
    # it, and the registry views below (units/weapons/armoury/rules) read from
    # it — where printed names stop being strings.
    repository: TOWRepository
    # The turn's phases, assembled as values — each owns exactly the
    # rules in force it needs; none holds a reference back to the game.
    strategy: StrategyPhase
    movement: MovementPhase
    shooting: ShootingPhase
    combat: CombatPhase

    # The printed turn sequence, derived from the Phase vocabulary: each
    # member names the binding property below.
    phase_sequence: ClassVar[tuple[str, ...]] = tuple(phase.name.lower() for phase in Phase)

    @property
    def units(self) -> Registry[Unit]:
        """The unit datasheets, addressed by slug."""
        return self.repository.units

    @property
    def weapons(self) -> Registry[Weapon]:
        """The weapon profiles, addressed by slug."""
        return self.repository.weapons

    @property
    def armoury(self) -> Registry[Armour]:
        """The armour items, addressed by slug."""
        return self.repository.armoury

    @property
    def rules(self) -> Registry[Rule]:
        """The special rules, addressed by slug."""
        return self.repository.rules

    @classmethod
    def assemble(cls, repository: TOWRepository) -> "TOWGame":
        """Assemble a game from the loaded corpus, each phase on its program.

        Returns:
            The assembled game, its programs loaded with the corpus rules.
        """
        return cls(
            repository=repository,
            strategy=StrategyPhase(),
            movement=MovementPhase(
                program=load_program(STAND_AND_SHOOT, repository.rules),
                charging=load_program(CHARGE, repository.rules),
            ),
            shooting=ShootingPhase(program=load_program(VOLLEY, repository.rules)),
            combat=CombatPhase(program=load_program(ROUND, repository.rules)),
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
            The fielded contingent, loadout resolved against the game's corpus.
        """
        return Contingent.field(unit, models, data=self.repository)

    def deploy(self, complement: Complement) -> Contingent:
        """Field a mustered list entry, resolving its chosen loadout.

        Returns:
            The fielded contingent, loadout resolved against the game's corpus.
        """
        return Contingent.field(complement, data=self.repository)

    def turn(self) -> Turn:
        """Begin a turn, to walk phase by phase with its rules in force.

        The turn takes no sides — units act in the phase calls at whatever
        number the question needs. Enter each phase through its context
        manager (``with turn.movement() as mv: ...``); the printed order is
        enforced, and the engagements charges form are fought in the Combat
        phase.

        Returns:
            A fresh turn over this game's phases.
        """
        return Turn(self.strategy, self.movement, self.shooting, self.combat)
