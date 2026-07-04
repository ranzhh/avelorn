"""A unit as mustered: the layers between the datasheet and the table.

The datasheet (:class:`~avelorn.tow.schema.unit.Unit`) prints what a unit
*may* be; this module holds the layers that make it concrete. A
:class:`Complement` is the unit as entered in an army list — a chosen
size and options, with the points and effective loadout that follow. A
:class:`Contingent` is the unit as fielded on the table — a model count
and, if it charged, the :class:`Charge` it made. Combat resolvers take
contingents; list validation will take complements.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from avelorn.tow.schema.unit import Unit, UnitOption


def _fold(
    base: list[str], options: list[UnitOption], adds_attr: str, removes_attr: str
) -> list[str]:
    """Apply each option's removes then adds to a base list, preserving order.

    Removes precede adds within an option, so an option can replace a name;
    an add already present is a no-op.

    Returns:
        A new list: ``base`` minus removed names plus added ones, appended
        in option order.
    """
    result = list(base)
    for option in options:
        for name in getattr(option, removes_attr):
            if name in result:
                result.remove(name)
        for name in getattr(option, adds_attr):
            if name not in result:
                result.append(name)
    return result


class Complement(BaseModel):
    """A unit as entered in an army list: a datasheet, sized and equipped.

    The middle of three representations. :class:`~avelorn.tow.schema.unit.Unit`
    is the datasheet — it prints the *allowed* size and the *available*
    options, but not what was taken. A :class:`Contingent` is the body on
    the table. A ``Complement`` is the list entry between them: the chosen
    ``size`` (within the datasheet's allowed range) and the ``options``
    bought, from which its ``points`` and effective loadout follow. It says
    *how many* and *made up of what* — the two things a bare datasheet
    leaves open.

    ``options`` names entries from ``unit.options``; a chosen option's
    ``adds``/``removes`` fold into :attr:`equipment` and :attr:`special_rules`.
    Command and heterogeneous profiles (a champion, an embedded character —
    each its own profile) affect only ``points`` today: the fielded body is
    still homogeneous, so they are recorded, not yet resolved into distinct
    parts (#46). Options priced by a ``points_budget`` (a magic standard)
    contribute no fixed cost until magic items are modelled.
    """

    model_config = ConfigDict(extra="forbid")

    unit: Unit
    size: int = Field(ge=1)
    options: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_against_datasheet(self) -> Self:
        allowed = self.unit.unit_size
        if self.size < allowed.min:
            raise ValueError(f"size {self.size} is below the unit's minimum {allowed.min}")
        if allowed.max is not None and self.size > allowed.max:
            raise ValueError(f"size {self.size} exceeds the unit's maximum {allowed.max}")
        if len(set(self.options)) != len(self.options):
            raise ValueError(f"options contains duplicates: {self.options}")
        available = {option.name for option in self.unit.options}
        unknown = [name for name in self.options if name not in available]
        if unknown:
            raise ValueError(f"options not offered by {self.unit.name}: {unknown}")
        return self

    @property
    def _chosen(self) -> list[UnitOption]:
        # The chosen options in the datasheet's own order, so points and the
        # loadout folds are deterministic however `options` happened to be written.
        picked = set(self.options)
        return [option for option in self.unit.options if option.name in picked]

    @property
    def points(self) -> int:
        """The complement's points: the models plus the options bought.

        A flat ``points`` option costs once per unit, or once per model when
        ``per_model``. ``points_budget`` options add nothing yet (see the
        class docstring).

        Returns:
            The total points cost.
        """
        total = self.size * self.unit.points
        for option in self._chosen:
            if option.points is not None:
                total += option.points * (self.size if option.per_model else 1)
        return total

    @property
    def equipment(self) -> list[str]:
        """The datasheet equipment after the chosen options' adds and removes.

        Returns:
            The effective equipment, in datasheet-then-added order.
        """
        return _fold(self.unit.equipment, self._chosen, "adds_equipment", "removes_equipment")

    @property
    def special_rules(self) -> list[str]:
        """The datasheet special rules after the chosen options' adds and removes.

        Returns:
            The effective special rules, in datasheet-then-added order.
        """
        return _fold(self.unit.special_rules, self._chosen, "adds_rules", "removes_rules")


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
    :class:`Complement` (list-legal size, chosen options) and bakes its
    loadout into the datasheet the engine reads.

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

    @classmethod
    def deploy(cls, complement: Complement, charge: Charge | None = None) -> "Contingent":
        """Field a :class:`Complement` as a contingent.

        The complement's chosen loadout — its equipment and special rules
        after its options' adds and removes — is baked into the datasheet the
        engine reads, so the contingent fights with what was bought, not the
        printed profile. The chosen ``size`` becomes ``models``.

        Args:
            complement: The list entry to field.
            charge: The charge this contingent made this turn, if any.

        Returns:
            The fielded contingent.
        """
        fielded = complement.unit.model_copy(
            update={
                "equipment": complement.equipment,
                "special_rules": complement.special_rules,
            }
        )
        return cls(fielded, complement.size, charge)
