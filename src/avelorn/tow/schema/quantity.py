"""The quantities a rule's operation changes, and the dice rolls an amount may be."""

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    CHARGE_ROLL = "charge-roll"
    MAXIMUM_CHARGE_RANGE = "maximum-charge-range"


_DICE_QUANTITY = re.compile(r"^D(?P<sides>[36])(?:\+(?P<plus>\d+))?$")


class DiceQuantity(BaseModel):
    """A printed quantity decided by a dice roll: "D6", "D3", "D3+1".

    The dice form of a rule's bracketed parameter -- "Often, this is
    determined by the roll of a dice" (Stomp Attacks, Impact Hits). One
    die plus a flat addend covers every printed instance; a wider form
    (2D6, say) joins when a rule prints one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sides: Literal[3, 6]
    plus: int = Field(default=0, ge=0)

    @classmethod
    def parse(cls, printed: str) -> "DiceQuantity | None":
        """Read a printed dice quantity off its text.

        Returns:
            The parsed quantity, or None when the text is not one.
        """
        match = _DICE_QUANTITY.match(printed)
        if match is None:
            return None
        sides: Literal[3, 6] = 3 if match.group("sides") == "3" else 6
        return cls(sides=sides, plus=int(match.group("plus") or 0))

    def __str__(self) -> str:
        """The quantity as printed.

        Returns:
            The text :meth:`parse` reads.
        """
        return f"D{self.sides}" + (f"+{self.plus}" if self.plus else "")
