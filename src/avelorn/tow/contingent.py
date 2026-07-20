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
from avelorn.tow.engine.rules import (
    EffectiveCharacteristic,
    effective_fighting_ranks,
    printed_rule,
)
from avelorn.tow.muster import Complement
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Condition, Rule
from avelorn.tow.schema.unit import Characteristic, Unit
from avelorn.tow.schema.weapon import Weapon


@dataclass(frozen=True)
class Loadout:
    """A contingent's gear and rules resolved to entries, at fielding time.

    Built at :meth:`Contingent.field` — the muster boundary is where a
    printed name stops being a string. The armour is what save resolution
    will read; the weapons are what a per-action choice will pick from;
    ``rules`` are the unit's special rules that resolve against the rule
    data — each the rule exactly as printed, parameters substituted, by
    the engine's one resolution convention
    (:func:`~avelorn.tow.engine.rules.printed_rule`).

    The two halves miss differently, by design. Equipment coverage is
    complete, so an unresolvable equipment name fails the deploy. Rule
    entries exist only for what the engine can honour, so a rule without
    one is the norm — unit rules without entries ride along printed, in
    :attr:`unresolved_rules`, and keep feeding the "not factored" notes
    rather than silently vanishing, and a weapon-rule name absent from
    :attr:`weapon_rules` compiles to unfactored the same way.
    """

    weapons: tuple[Weapon, ...]
    armour: tuple[Armour, ...]
    rules: tuple[Rule, ...]
    unresolved_rules: tuple[str, ...]
    # Every rule name printed on a carried weapon's profiles that has an
    # entry, resolved as printed — the per-action compile looks names up
    # here instead of in a registry. Names without entries are simply
    # absent and compile to unfactored, as ever.
    weapon_rules: Mapping[str, Rule] = field(default_factory=dict)

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
    bonuses each grants differ (#28) — so all three are distinguished
    here, and each arc carries its own printed numbers.
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


@dataclass(frozen=True)
class Charge:
    """A charge move: how far it carried, into which arc. A pure record.

    Both facts are read by the rules the charge feeds — the Combat-phase
    Initiative bonus computes in
    :func:`~avelorn.tow.phases.combat.effective_initiative`, and the
    flank/rear combat-result bonuses are a still-deferred concern (#28).
    The arc has no default: which arc a charge struck is a fact of the
    move, not a parameter to assume.
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

    @property
    def initiative_bonus(self) -> int:
        """The Initiative bonus this charge grants its charger.

        +1 per full inch moved, capped by the arc struck (+3 into the
        front, +4 into the flank or rear; the-combat-phase/charging-units).
        A charge knows only its own contribution: the rulebook's total
        Initiative ceiling of 10 is the striking-order assembler's to
        apply (:func:`~avelorn.tow.phases.combat.effective_initiative`),
        not the charge's.

        Returns:
            The arc-capped Initiative bonus, +0 for a standing start.
        """
        return min(self.full_inches, self.arc.initiative_cap)


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

    @property
    def rear_rank_sizes(self) -> tuple[int, ...]:
        """The model count of each rank behind the front, front to back.

        Empty for a single-rank formation. The ranks a Volley Fire draws
        its extra shots from, and the supporting ranks a melee will draw
        on, read their sizes from here.
        """
        sizes = [self.frontage] * self.full_ranks
        if self.remainder:
            sizes.append(self.remainder)
        return tuple(sizes[1:])

    def front_ranks(self, depth: int) -> int:
        """The models standing in the front ``depth`` ranks.

        The front rank plus the ``depth - 1`` ranks directly behind it —
        the geometry a fighting rank of a given depth draws its models
        from. ``depth`` of one is just the front rank (:attr:`files`).

        Returns:
            The model count in the front ``depth`` ranks.
        """
        return self.files + sum(self.rear_rank_sizes[: depth - 1])


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
    (:func:`~avelorn.tow.phases.combat.fight`,
    :func:`~avelorn.tow.phases.movement.stand_and_shoot`), so a contingent
    is armed before it fights or shoots.

    Today a contingent is a single homogeneous body — one profile (the
    rank-and-file, ``unit.profiles[0]``). A real contingent can be
    heterogeneous: rank and file plus a champion, plus an embedded
    character, each its own profile, Attacks and weapon. That is
    deliberately not modelled yet (#46); when it is, this grows a notion of
    *parts* and the single-body fields become the one-part case. Callers read
    only ``profiles[0]``, so the assumption stays localized to that migration.
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
    # Read by the movement-gated rules (Moving and Shooting; Volley Fire's
    # stationary condition) and by :func:`~avelorn.tow.phases.combat.fight`
    # for the striking order's charge Initiative bonus.
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

    @property
    def rank_bonus(self) -> int:
        """The combat-result Rank Bonus this contingent's formation claims.

        +1 for each rank behind the first that is wide enough to count,
        capped by the troop type. A full rank at the frontage counts; an
        incomplete rear rank counts when it holds the troop type's
        required models. A troop type that does not rank up claims none.
        Counted from the fielded models — the round's starting formation.

        Returns:
            The Rank Bonus, from 0 up to the troop type's maximum.
        """
        profile = self.unit.rank_and_file
        per_rank = profile.models_per_rank
        if per_rank is None or self.frontage < per_rank:
            return 0
        formation = self.formation
        rear = 1 if formation.remainder >= per_rank else 0
        ranks_behind_first = formation.full_ranks + rear - 1
        return min(max(ranks_behind_first, 0), profile.max_rank_bonus)

    def fighting_ranks(self) -> EffectiveCharacteristic:
        """How many ranks fight at full Attacks, and the rules behind the count.

        One rank by default — only the front rank fights
        (the-combat-phase/who-can-fight) — deepened by the rank-modifying
        rules the contingent carries: Press of Battle takes it to two, except
        on a turn it charged. The rules are read from the loadout and gated on
        the contingent's own charge, so the depth holds whatever a survivor
        count; ``factored`` / ``unfactored`` name the rules evaluated into it,
        for the combat notes.

        Returns:
            The fighting-rank depth, with the rule names factored into it and
            those left unfactored.
        """
        return effective_fighting_ranks(
            1, self.loadout.rules, {Condition.CHARGED: self.movement.charge is not None}
        )

    def fighting_rank(self) -> int:
        """The models that fight at their full Attacks — the fighting rank.

        The front rank, in base contact with the foe, plus the ranks a rule
        deepens it to (:meth:`fighting_ranks`); the whole front rank is taken
        to be engaged, an equally wide foe. Models further back press forward
        but do not fight.

        Returns:
            The number of models in the fighting rank.
        """
        return self.formation.front_ranks(self.fighting_ranks().value)

    def melee_attacks(self) -> int:
        """The attacks this body throws striking a frontal melee.

        Its fighting rank (:meth:`fighting_rank`) each make their full
        Attacks. The supporting attacks that some weapons grant the rank
        behind (Fight in Extra Rank) are a separate rule, not modelled here.
        A profile with no printed Attacks throws none.

        Returns:
            The number of attacks thrown this round.
        """
        attacks_per_model = self.unit.profiles[0][Characteristic.ATTACKS] or 0
        return self.fighting_rank() * attacks_per_model

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
        so a name matching no weapon or armour entry is an error; a special rule
        without an entry rides along printed (:class:`Loadout`).

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
                equipment matches no weapon or armour entry, or the datasheet's
                troop-type profile is unresolved.
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
    # The muster-boundary resolution both constructors share: equipment
    # partitions into weapons and armour, special rules resolve where
    # entries exist and ride along printed where they do not. Unknown
    # equipment comes back for the constructor to refuse — coverage is
    # complete, so a miss is a typo in the list.
    wielded, rest = weapons.resolve(unit.equipment)
    worn, unknown = armoury.resolve(rest)
    resolved: list[Rule] = []
    unresolved: list[str] = []
    # The unit's own printed rules, then the rules its troop type confers
    # (Press of Battle, ...): both resolve the same way — an entry with
    # effects joins the loadout, a name without one rides along printed and
    # feeds the "not factored" notes.
    troop_type = unit.troop_type_profile
    conferred = troop_type.special_rules if troop_type is not None else ()
    for printed in (*unit.special_rules, *conferred):
        entry = printed_rule(printed, rules)
        if entry is None:
            unresolved.append(printed)
        else:
            resolved.append(entry)
    weapon_rules: dict[str, Rule] = {}
    for weapon in wielded:
        for profile in weapon.profiles:
            for printed in profile.special_rules:
                if printed not in weapon_rules and (entry := printed_rule(printed, rules)):
                    weapon_rules[printed] = entry
    loadout = Loadout(
        tuple(wielded), tuple(worn), tuple(resolved), tuple(unresolved), weapon_rules
    )
    return loadout, unknown
