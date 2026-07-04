"""The army-list layer: a unit as mustered into a list.

The datasheet (:class:`~avelorn.tow.schema.unit.Unit`) prints what a unit
*may* be; a :class:`Complement` is the unit as entered in an army list —
a chosen size and options, with the points and effective loadout that
follow. List validation will take complements; to put one on the table,
:meth:`~avelorn.tow.combat.contingent.Contingent.deploy` fields it as
the gameplay-side body.
"""

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
    options, but not what was taken. A
    :class:`~avelorn.tow.combat.contingent.Contingent` is the body on
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
