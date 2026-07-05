"""A unit as fielded on the table, and the record of a charge move.

The gameplay-side counterpart of the army-list layer
(:mod:`avelorn.tow.muster`): a :class:`Contingent` is the body the combat
resolvers take — a datasheet plus the models actually standing.
:class:`Charge` records a charge move — event data, carried by the
action that resolves it (:func:`~avelorn.tow.combat.charge.charge`, via
the :class:`~avelorn.tow.combat.context.CombatContext`), never by the
unit. Fielding is also where printed equipment names stop being
strings: :meth:`Contingent.deploy` resolves them into a
:class:`Loadout`.
"""

from dataclasses import dataclass
from enum import StrEnum

from avelorn.core.registry import Registry
from avelorn.tow.muster import Complement
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon


@dataclass(frozen=True)
class Loadout:
    """A contingent's equipment resolved to entries: weapons and armour worn.

    Built at :meth:`Contingent.deploy` — the muster boundary is where a
    printed equipment name stops being a string. The armour is what save
    resolution will read; the weapons are what a per-action choice will
    pick from. Special rules are not carried here yet: they stay printed
    strings on the fielded datasheet until rule resolution moves onto
    this seam, tolerating rules whose entries are not imported yet.
    """

    weapons: tuple[Weapon, ...]
    armour: tuple[Armour, ...]


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
    :func:`~avelorn.tow.combat.melee.effective_initiative`, and the
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


@dataclass(frozen=True)
class Contingent:
    """A unit as fielded: its datasheet and the models on the table.

    The datasheet (:class:`~avelorn.tow.schema.unit.Unit`) is a template —
    it carries the *allowed* size, not how many models stand on the table —
    so ``models`` supplies the fielded count. Nothing about the turn rides
    here: a charge is an action's event data
    (:class:`~avelorn.tow.combat.context.CombatContext`), not unit state.

    Construct one directly — ``Contingent(unit, models)`` — for an
    arbitrary body on the table: a post-casualty remnant, or an isolated count
    for analysis, neither of which need be a legal army-list size. To field a
    mustered list entry instead, use :meth:`deploy`, which takes a
    :class:`~avelorn.tow.muster.Complement` (list-legal size, chosen
    options) and bakes its loadout into the datasheet the engine reads.

    The weapon in use is *not* carried here: it is a per-action choice, so
    the same contingent shoots with its bow one moment and fights the
    ensuing melee with a hand weapon the next. Each action takes the chosen
    weapon (:func:`~avelorn.tow.combat.melee.fight`,
    :func:`~avelorn.tow.combat.charge.stand_and_shoot`).

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
    loadout: Loadout | None = None  # resolved by deploy(); None on direct construction

    @classmethod
    def deploy(
        cls,
        complement: Complement,
        *,
        weapons: Registry[Weapon],
        armoury: Registry[Armour],
    ) -> "Contingent":
        """Field a :class:`~avelorn.tow.muster.Complement`, resolving its equipment.

        The complement's chosen loadout — its equipment and special rules
        after its options' adds and removes — is baked into the datasheet the
        engine reads, so the contingent fights with what was bought, not the
        printed profile; the chosen ``size`` becomes ``models``. The
        equipment names also resolve against the weapon and armour data into
        a :class:`Loadout`. A name matching neither is an error, not a note:
        the data covers every unit-referenced item (a test pins it), so at
        this seam a miss is a typo in the list, and the human building the
        list is the one to tell.

        Args:
            complement: The list entry to field.
            weapons: Weapon entries, resolving printed equipment names.
            armoury: Armour entries, resolving printed equipment names.

        Returns:
            The fielded contingent, loadout resolved.

        Raises:
            ValueError: a piece of equipment matches no weapon or armour
                entry.
        """
        equipment = complement.equipment
        wielded, rest = weapons.resolve(equipment)
        worn, unknown = armoury.resolve(rest)
        if unknown:
            raise ValueError(
                f"{complement.unit.name}: equipment matches no weapon or armour: {unknown}"
            )
        fielded = complement.unit.model_copy(
            update={
                "equipment": equipment,
                "special_rules": complement.special_rules,
            }
        )
        return cls(fielded, complement.size, Loadout(tuple(wielded), tuple(worn)))
