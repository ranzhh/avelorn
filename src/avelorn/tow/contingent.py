"""A unit as fielded on the table, and the record of a charge move.

The gameplay-side counterpart of the army-list layer
(:mod:`avelorn.tow.muster`): a :class:`Contingent` is the body the combat
resolvers take — a datasheet plus the models actually standing, and the
turn actions it took (whether it moved, its :class:`Charge`). Fielding is
also where printed names stop being strings: :meth:`Contingent.field`
resolves equipment and special rules into a :class:`Loadout`.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from avelorn.core.registry import Registry
from avelorn.tow.data import TOWRepository, default_repository
from avelorn.tow.muster import Complement
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import Rule, bind
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon, WeaponProfile


@dataclass(frozen=True)
class Loadout:
    """A contingent's gear and rules resolved to entries, at fielding time.

    Built at :meth:`Contingent.field` — the muster boundary is where a
    printed name stops being a string. The armour is what save resolution
    will read; the weapons are what a per-action choice will pick from.
    ``own`` are the datasheet's special rules and ``conferred`` the troop
    type's, each bound to its X (:func:`~avelorn.tow.schema.rule.bind`).
    ``bound`` holds the rules the weapons' profiles print, bound, by
    reference: a weapon profile looks its rules up there.

    Equipment coverage is complete, so an unresolvable equipment name fails
    the deploy, and so does a rule reference that does not bind.
    """

    weapons: tuple[Weapon, ...]
    armour: tuple[Armour, ...]
    own: tuple[Rule, ...]
    conferred: tuple[Rule, ...] = ()
    bound: Mapping[RuleRef, Rule] = field(default_factory=dict)

    @classmethod
    def carrying(
        cls,
        weapons: Sequence[Weapon],
        armour: Sequence[Armour],
        own: Sequence[Rule],
        conferred: Sequence[Rule] = (),
        *,
        rules: Mapping[str, Rule],
    ) -> "Loadout":
        """A loadout whose weapons' rules are bound against ``rules``.

        Returns:
            The loadout, its ``bound`` index filled.
        """
        bound = {
            ref: bind(ref, rules)
            for weapon in weapons
            for profile in weapon.profiles
            for ref in profile.special_rules
        }
        return cls(tuple(weapons), tuple(armour), tuple(own), tuple(conferred), bound)

    @property
    def rules(self) -> tuple[Rule, ...]:
        """The unit's own rules, then those its troop type confers."""
        return (*self.own, *self.conferred)

    def profile_rules(self, profile: WeaponProfile) -> list[Rule]:
        """The bound rules a weapon profile prints.

        Returns:
            One rule per reference on the profile, in printed order.
        """
        return [self.bound[ref] for ref in profile.special_rules]

    def weapon(self, name: str) -> Weapon:
        """The carried weapon with the given printed name.

        The text boundary's resolver: a CLI argument or an API request
        names the weapon, this turns it into the entry once, and the
        engine works with the object from there
        (:meth:`Contingent.wielding` arms a contingent through it).

        Returns:
            The carried weapon entry.

        Raises:
            ValueError: no carried weapon has that name — a unit fights
                with what it carries.
        """
        for weapon in self.weapons:
            if weapon.name == name:
                return weapon
        carried = ", ".join(weapon.name for weapon in self.weapons) or "nothing"
        raise ValueError(f"no {name!r} in this loadout; carried: {carried}")


class ChargeArc(StrEnum):
    """Which arc a charge struck.

    The rulebook caps the charge Initiative bonus per arc (front vs flank
    or rear), but flank and rear diverge elsewhere — the combat-result
    bonuses each grants differ — so all three are distinguished here, and
    each arc carries its own printed numbers.
    """

    FRONT = "front"
    FLANK = "flank"
    REAR = "rear"

    @property
    def initiative_cap(self) -> int:
        """The arc's cap on the charge Initiative bonus.

        Returns:
            +3 into the front arc, +4 into the flank or rear
            (the-combat-phase/charging-units).
        """
        return 3 if self is ChargeArc.FRONT else 4

    @property
    def combat_result_bonus(self) -> int:
        """The combat-result points a side claims for striking this arc.

        Returns:
            +1 for a flank attack, +2 for a rear attack, none for a
            frontal one (the-combat-phase/combat-result-score).
        """
        return {ChargeArc.FRONT: 0, ChargeArc.FLANK: 1, ChargeArc.REAR: 2}[self]


@dataclass(frozen=True)
class Charge:
    """A charge move: how far it carried, into which arc. A pure record.

    Both facts are read by the round a charge opens
    (:func:`~avelorn.tow.round.fight_round`): the distance sets the
    charger's Initiative bonus, and the arc its combat-result points. The
    arc has no default: which arc a charge struck is a fact of the move,
    not a parameter to assume.
    """

    full_inches: int
    arc: ChargeArc

    def __post_init__(self) -> None:
        """Reject a nonsensical move.

        Raises:
            ValueError: the charge distance is negative — a programming
                error, not a zero bonus.
        """
        if self.full_inches < 0:
            raise ValueError(f"a charge cannot move a negative distance ({self.full_inches})")


class MovementKind(StrEnum):
    """The kind of move a contingent made in its Movement phase.

    The closed set of movements the engine distinguishes today. Flee is a
    real charge reaction (:class:`~avelorn.tow.phases.movement.Flee`) but is
    not modelled yet, so it has no member here until a resolver needs to
    tell a fled unit apart from one that merely moved.
    """

    STATIONARY = "stationary"
    MARCHED = "marched"
    CHARGED = "charged"


@dataclass(frozen=True)
class Movement:
    """What a contingent did in its Movement phase, as one tagged value.

    A contingent's movement is a single fact with a definite default — a
    freshly fielded body is :meth:`stationary` — that the shooting and
    combat resolvers read through its derived :attr:`moved` (did it move
    at all, a charge counting as a move) and its :attr:`charge` (the charge
    it made, if any). Folding what were two independent ``Contingent``
    fields (a ``moved`` flag beside an optional ``charge``) into one value
    means the pair can never disagree: a charge is a move, so here it is one
    by construction.

    Build through the case factories (:meth:`stationary`, :meth:`march`,
    :meth:`charged`) rather than the raw constructor — they are the
    movements the engine allows, and they keep :attr:`charge` present
    exactly when the move is a charge.
    """

    kind: MovementKind
    # The charge this move was, when the kind is CHARGED; None otherwise, so
    # a charger's Movement is self-contained — how far it came and into
    # which arc travel with the fact that it charged, one value to thread.
    charge: Charge | None = None

    def __post_init__(self) -> None:
        """Reject a charge that disagrees with its kind.

        Raises:
            ValueError: a charge is carried without the kind being a charge,
                or a charge kind carries none — a programming error the
                factories cannot produce.
        """
        if (self.kind is MovementKind.CHARGED) != (self.charge is not None):
            raise ValueError(
                f"a {self.kind} movement carries "
                f"{'no charge' if self.charge is None else 'a charge'}"
            )

    @classmethod
    def stationary(cls) -> "Movement":
        """The default: a body that did not move this turn.

        Returns:
            The stationary movement.
        """
        return cls(MovementKind.STATIONARY)

    @classmethod
    def march(cls) -> "Movement":
        """A move that was not a charge — "moved for any reason" short of one.

        Returns:
            The marched (moved, not charged) movement.
        """
        return cls(MovementKind.MARCHED)

    @classmethod
    def charged(cls, charge: Charge) -> "Movement":
        """A charge move, carrying the :class:`Charge` it was.

        Returns:
            The charged movement, carrying ``charge``.
        """
        return cls(MovementKind.CHARGED, charge)

    @property
    def moved(self) -> bool:
        """Whether the contingent moved at all this turn — a charge included.

        The fact the movement-gated rules read (Moving and Shooting; Volley
        Fire's stationary condition): true for every move, a charge among
        them, false only for a standing start.
        """
        return self.kind is not MovementKind.STATIONARY


@dataclass(frozen=True)
class Formation:
    """A body of models arrayed a fixed number wide, in ranks and files.

    Pure geometry: how ``models`` stand when the formation is ``frontage``
    models wide. ``files`` is the width (the front rank's models), ``ranks``
    the depth, ``full_ranks`` the complete ranks at the full width, and
    ``remainder`` the models in an incomplete rear rank (0 when the last
    rank is full). Knows nothing of troop type or combat.
    """

    models: int
    frontage: int

    @property
    def files(self) -> int:
        """The width: models standing in the front (widest) rank."""
        return min(self.models, self.frontage)

    @property
    def full_ranks(self) -> int:
        """The number of complete ranks, each at the full frontage."""
        return self.models // self.frontage

    @property
    def remainder(self) -> int:
        """Models in the incomplete rear rank; 0 when the last rank is full."""
        return self.models % self.frontage

    @property
    def ranks(self) -> int:
        """The depth: how many ranks, the rear one possibly incomplete."""
        return self.full_ranks + (1 if self.remainder else 0)


@dataclass(frozen=True)
class Contingent:
    """A unit as fielded: its datasheet and the models on the table.

    The datasheet (:class:`~avelorn.tow.schema.unit.Unit`) is a template —
    it carries the *allowed* size, not how many models stand on the table —
    so ``models`` supplies the fielded count. A unit's own turn actions
    ride here: its ``movement`` this turn — one :class:`Movement` value,
    defaulting to stationary for a freshly fielded body — records both
    whether it moved and the charge it made, if any (a charge is a move, so
    the two can never disagree). The relational facts of an engagement — the
    range to a target, the round of a combat — are not one unit's state and
    stay parameters of the resolving action.

    Two constructors resolve a loadout at the muster boundary, split by what
    you hold. :meth:`deploy` starts from a *name*: a datasheet slug (plus any
    options), mustered and fielded against the game data. :meth:`field` starts
    from an *object* in hand — a :class:`~avelorn.tow.muster.Complement` you
    mustered (list-legal size, chosen options, loadout baked into the datasheet
    the engine reads), or a bare :class:`~avelorn.tow.schema.unit.Unit` at any
    model count, so a remnant or an isolated what-if needs no legal list size.
    Neither threads registries: both resolve against a
    :class:`~avelorn.tow.data.TOWRepository` — the process-wide default, or one
    injected as ``data`` (which is how tests field against doctored data).
    Bodies whose loadout already exists are derived from one that does, through
    the fluent copies: a post-casualty remnant is :meth:`remove_casualties`, a
    mover is :meth:`after`, a charger :meth:`charging`.

    The weapon in use is a per-action choice — the same contingent shoots
    with its bow one moment and fights the ensuing melee with a hand weapon
    the next — so it rides here as a *selected* weapon, set for the action
    through :meth:`wielding` (which picks one from the loadout by name) and
    read back through :meth:`in_hand`. A freshly fielded body has none in
    hand; every verb reads the wielded weapon off the side that acts
    (:func:`~avelorn.tow.round.fight_round`,
    :func:`~avelorn.tow.volley.stand_and_shoot`), so a contingent
    is armed before it fights or shoots.

    A contingent is one body of models; :meth:`~avelorn.tow.fielding.Fielding.of`
    splits it into the parts a program resolves: its rank and file, each
    champion bought, and the mount each rides.
    """

    unit: Unit
    models: int
    loadout: Loadout
    # The formation's width in models (its files). A unit on the table is
    # always in some formation, so this is a concrete width, resolved at
    # the fielding boundary. (Skirmishers, who form no ranks, are not
    # modelled yet.)
    frontage: int
    # What the unit did in its Movement phase, as one tagged value: whether
    # it moved and the charge it made, if any (a charge is a move, folded
    # here so the two never disagree). A freshly fielded body is stationary;
    # a caller that moved it sets this through :meth:`after` / :meth:`charging`.
    movement: Movement = field(default_factory=Movement.stationary)
    # The weapon selected for the current action, picked from the loadout by
    # name through :meth:`wielding`. A per-action choice (a unit shoots its
    # bow, then fights the ensuing melee with a hand weapon), so it is not
    # fixed at fielding: None until the contingent is armed, read back
    # through :meth:`in_hand`.
    weapon: Weapon | None = None

    def __post_init__(self) -> None:
        """Reject a frontage that is not a positive width.

        Raises:
            ValueError: ``frontage`` is below one model wide.
        """
        if self.frontage < 1:
            raise ValueError(f"frontage must be at least 1 model wide, got {self.frontage}")

    @property
    def formation(self) -> Formation:
        """How the contingent's models stand in ranks and files.

        Returns:
            The formation geometry for this contingent's models and frontage.
        """
        return Formation(self.models, self.frontage)

    def in_hand_rules(self) -> list[Rule]:
        """The resolved rules on the weapon in hand's Combat profile.

        The wielded weapon's Combat-profile references, bound in the
        loadout (:meth:`Loadout.profile_rules`) — the rules that ride with the weapon a
        contingent chose to swing (a great weapon's Strike Last, a thrusting
        spear's Fight in Extra Rank). Empty when nothing is in hand or the
        weapon has no Combat profile.

        Returns:
            The resolved in-hand weapon rules, empty when none apply.
        """
        weapon = self.weapon
        profile = weapon.combat_profile if weapon is not None else None
        if profile is None:
            return []
        return self.loadout.profile_rules(profile)

    def after(self, movement: Movement) -> "Contingent":
        """This contingent with its Movement-phase ``movement`` set.

        The one place a fielded body records what it did this turn, hiding
        the frozen-dataclass copy: ``contingent.after(Movement.march())``
        reads as the move it was, not a field assignment.

        Returns:
            A copy with the given movement; the original is unchanged.
        """
        return replace(self, movement=movement)

    def charging(self, move: Charge) -> "Contingent":
        """This contingent as the charger of ``move``: its movement a charge.

        The charge path's :meth:`after`, spelt for its one case — the fight
        assembler and the charge verb both hand a :class:`Charge` and want
        the charger it belongs to.

        Returns:
            A copy whose movement is that charge; the original is unchanged.
        """
        return self.after(Movement.charged(move))

    def remove_casualties(self, casualties: int) -> "Contingent":
        """This contingent with ``casualties`` models removed after a round.

        The same body, fewer models: loadout, datasheet, frontage and
        movement all ride along, only the count drops. The Remove Casualties
        step, everywhere a round's losses are applied to a side — spelt by
        what was felled, not by the residual.

        Returns:
            A copy with ``models`` reduced by ``casualties``; the original
            is unchanged.
        """
        return replace(self, models=self.models - casualties)

    def wielding(self, name: str) -> "Contingent":
        """This contingent armed with the carried weapon named ``name``.

        The one place a fielded body picks the weapon it acts with — from
        its own loadout, by printed name (:meth:`Loadout.weapon`, which
        rejects a name the loadout does not carry), so only what was fielded
        can be fought or fired with. A per-action choice, spelt as the arming
        it is: ``spearmen.wielding("Thrusting Spear")`` reads as the weapon
        taken in hand, not a field assignment. Read it back with
        :meth:`in_hand`.

        Returns:
            A copy wielding that weapon; the original is unchanged.
        """
        return replace(self, weapon=self.loadout.weapon(name))

    def in_hand(self) -> Weapon:
        """The weapon this contingent was armed to act with.

        The strict reader, used by melee: the choice is made once — through
        :meth:`wielding` — and read off the side that acts, never threaded
        through the call. A fight names its weapon; there is no default,
        because a unit that carries a special weapon (a thrusting spear, a
        great weapon) almost always means to swing it, and a silent fallback
        would quietly fight with the wrong one. Shooting relaxes this through
        :meth:`shooting_weapon`, where the sole missile weapon is unambiguous.

        Returns:
            The selected weapon.

        Raises:
            ValueError: nothing is in hand — the contingent was never armed.
        """
        if self.weapon is None:
            raise ValueError(
                f"{self.unit.name} has no weapon in hand; arm it with .wielding(name)"
            )
        return self.weapon

    def shooting_weapon(self) -> Weapon:
        """The missile weapon this contingent fires.

        Shooting keeps arming optional where the choice cannot be mistaken:
        a contingent armed through :meth:`wielding` fires that weapon, but an
        unarmed one that carries exactly one missile weapon fires it without
        ceremony — the common case, a unit of archers with only its bow.
        Melee has no such default (see :meth:`in_hand`); shooting does,
        because a lone bow is the only thing it could mean.

        Returns:
            The weapon in hand, or — when none is — the sole carried missile
            weapon.

        Raises:
            ValueError: unarmed and the loadout carries no missile weapon, or
                more than one, so the choice cannot be made for the caller.
        """
        if self.weapon is not None:
            return self.weapon
        missile = [weapon for weapon in self.loadout.weapons if weapon.missile_profile is not None]
        if len(missile) == 1:
            return missile[0]
        if not missile:
            raise ValueError(f"{self.unit.name} carries no missile weapon to shoot with")
        carried = ", ".join(weapon.name for weapon in missile)
        raise ValueError(
            f"{self.unit.name} carries several missile weapons ({carried}); "
            "arm it with .wielding(name)"
        )

    @classmethod
    def deploy(
        cls,
        slug: str,
        models: int,
        options: Sequence[str] = (),
        *,
        data: TOWRepository | None = None,
        frontage: int | None = None,
    ) -> "Contingent":
        """Deploy a unit by name — the quick way onto the table.

        You have a name: this looks up the datasheet ``slug`` in ``data`` — the
        process-wide :func:`~avelorn.tow.data.default_repository` when omitted —
        musters it at ``models`` with the chosen ``options`` (through a
        :class:`~avelorn.tow.muster.Complement`, so the size must be list-legal
        and each option offered by the datasheet), and fields it. Inject ``data``
        to deploy against alternate or doctored data (tests do).

        When you already hold the object, :meth:`field` it instead — a
        :class:`~avelorn.tow.muster.Complement` you mustered, or a bare
        :class:`~avelorn.tow.schema.unit.Unit` at any model count (a remnant or
        a what-if, which a legal muster would reject).

        Args:
            slug: The datasheet's slug, resolved against ``data.units``.
            models: The fielded size; must fall in the datasheet's allowed range.
            options: Option names to buy, each offered by the datasheet.
            data: The corpus to resolve against; the process-wide default when omitted.
            frontage: The formation width in files; the troop type's default
                width when omitted.

        Returns:
            The fielded contingent, loadout resolved.
        """
        repository = data if data is not None else default_repository()
        complement = Complement(unit=repository.units[slug], size=models, options=list(options))
        return cls.field(complement, data=repository, frontage=frontage)

    @classmethod
    def field(
        cls,
        source: "Unit | Complement",
        models: int | None = None,
        *,
        data: TOWRepository | None = None,
        frontage: int | None = None,
    ) -> "Contingent":
        """Field an object in hand: a mustered Complement, or a bare datasheet.

        The precise counterpart to :meth:`deploy` (which starts from a name).
        ``source`` is one of two things:

        * a :class:`~avelorn.tow.muster.Complement` — its chosen loadout
          (equipment and special rules after its options' adds and removes)
          baked into the datasheet the engine reads, and its ``size`` the
          fielded count; the ``models`` argument is ignored.
        * a bare :class:`~avelorn.tow.schema.unit.Unit` — its printed,
          optionless loadout at ``models`` models, any count, so a remnant or
          an isolated what-if needs no legal list size (it does not route
          through a Complement).

        Names resolve against ``data`` — the process-wide
        :func:`~avelorn.tow.data.default_repository` when omitted; inject it to
        field against alternate or doctored data. Equipment coverage is complete,
        so a name matching no weapon or armour entry is an error, as is a rule
        reference that does not bind (:class:`Loadout`).

        Args:
            source: A mustered Complement, or a bare datasheet to field.
            models: The fielded size, required for a bare datasheet; ignored for
                a Complement (whose own ``size`` is used).
            data: The corpus to resolve against; the process-wide default when omitted.
            frontage: The formation width in files; the troop type's default
                width when omitted.

        Returns:
            The fielded contingent, loadout resolved.

        Raises:
            ValueError: a bare datasheet is given without ``models``, a piece of
                equipment matches no weapon or armour entry, a rule reference does
                not bind, or the datasheet's troop-type profile is unresolved.
        """
        repository = data if data is not None else default_repository()
        if isinstance(source, Complement):
            size = source.size
            datasheet = source.unit.model_copy(
                update={"equipment": source.equipment, "special_rules": source.special_rules}
            )
        else:
            if models is None:
                raise ValueError("field(unit, models) needs a model count for a bare datasheet")
            size = models
            datasheet = source
        loadout, unknown = _resolve_loadout(
            datasheet,
            weapons=repository.weapons,
            armoury=repository.armoury,
            rules=repository.rules,
        )
        if unknown:
            raise ValueError(f"{datasheet.name}: equipment matches no weapon or armour: {unknown}")
        width = (
            frontage if frontage is not None else datasheet.rank_and_file.default_frontage(size)
        )
        return cls(datasheet, size, loadout, width)


def _resolve_loadout(
    unit: Unit,
    *,
    weapons: Registry[Weapon],
    armoury: Registry[Armour],
    rules: Registry[Rule],
) -> tuple[Loadout, list[str]]:
    wielded, rest = weapons.resolve(unit.equipment)
    worn, unknown = armoury.resolve(rest)
    troop_type = unit.troop_type_profile
    conferred = troop_type.special_rules if troop_type is not None else ()
    loadout = Loadout.carrying(
        wielded,
        worn,
        [bind(ref, rules) for ref in unit.special_rules],
        [bind(ref, rules) for ref in conferred],
        rules=rules,
    )
    return loadout, unknown
