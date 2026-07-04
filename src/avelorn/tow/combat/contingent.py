"""A unit as fielded on the table: the contingent and the charge it made.

The gameplay-side counterpart of the army-list layer
(:mod:`avelorn.tow.muster`): a :class:`Contingent` is the body the combat
resolvers take — a datasheet plus the models actually standing — and
:class:`Charge` is the charge move it may have made this turn, feeding
its Combat-phase Initiative bonus. Fielding is also where printed
equipment names stop being strings: :meth:`Contingent.deploy` resolves
them into a :class:`Loadout`.
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
    bonuses each grants differ (#28) — so all three are distinguished here.
    """

    FRONT = "front"
    FLANK = "flank"
    REAR = "rear"


@dataclass(frozen=True)
class Charge:
    """A charge move, feeding the charger's Combat-phase Initiative bonus.

    A model that charged gains +1 Initiative per full inch it moved before
    contact — capped at +3 into the enemy's front arc, +4 into its flank or
    rear (the-combat-phase/charging-units).
    :func:`~avelorn.tow.combat.melee.fight` caps the resulting Initiative
    at 10, as the rule requires. The flank/rear *combat-result* bonuses
    that same arc would grant are a separate, still-deferred concern
    (#28); only the Initiative modifier is read here.
    """

    full_inches: int
    arc: ChargeArc = ChargeArc.FRONT

    def initiative_bonus(self) -> int:
        """The Initiative modifier this charge grants its models.

        Returns:
            +1 per full inch moved, clamped to the arc's cap (+3 into the
            front, +4 into the flank or rear) and never below zero.
        """
        cap = 3 if self.arc is ChargeArc.FRONT else 4
        return min(max(self.full_inches, 0), cap)


@dataclass(frozen=True)
class Contingent:
    """A unit as fielded: its datasheet and the models on the table.

    The datasheet (:class:`~avelorn.tow.schema.unit.Unit`) is a template —
    it carries the *allowed* size, not how many models stand on the table —
    so ``models`` supplies the fielded count. ``charge`` is the charge this
    contingent made this turn, if any; its Initiative bonus decides who
    strikes first in :func:`~avelorn.tow.combat.melee.fight`, and a
    contingent that did not charge (any shooter among them) leaves it None.

    Construct one directly — ``Contingent(unit, models, charge)`` — for an
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
    charge: Charge | None = None
    loadout: Loadout | None = None  # resolved by deploy(); None on direct construction

    @classmethod
    def deploy(
        cls,
        complement: Complement,
        *,
        weapons: Registry[Weapon],
        armoury: Registry[Armour],
        charge: Charge | None = None,
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
            charge: The charge this contingent made this turn, if any.

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
        return cls(fielded, complement.size, charge, Loadout(tuple(wielded), tuple(worn)))
