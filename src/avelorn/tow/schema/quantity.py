"""The quantities a rule's operation changes."""

from enum import StrEnum


class Quantity(StrEnum):
    """A quantity an effect can change, in the rulebook's own modifier vocabulary.

    A closed, append-only enum: a member joins when an imported rule needs it.
    A profile :class:`~avelorn.tow.schema.unit.Characteristic` is the one
    quantity kept apart, a stat vocabulary used far beyond modifiers, so an
    operation's key is a Quantity or a Characteristic.
    """

    TO_HIT = "to-hit"
    ARMOUR_PIERCING = "armour-piercing"
    FIGHTING_RANKS = "fighting-ranks"
    COMBAT_RESULT = "combat-result"
    ARMOUR_VALUE = "armour-value"
    WARD_SAVE = "ward-save"
