"""The quantities a rule's operation changes, and the legacy seam that consumes each."""

from enum import StrEnum
from typing import assert_never

from avelorn.tow.schema.unit import Characteristic


class Seam(StrEnum):
    """Where an operation's quantity is consumed.

    A modifier's quantity lands in exactly one place, and the seam names it:
    the dice walk (roll quantities); the effective-characteristic query; the
    fighting-rank query; the combat-result fold; the armour fold, which
    improves the defender's armour value before its save; or the ward fold,
    which grants the defender the best warding value its rules confer.
    :meth:`ModifierEffect._ops_speak_to_one_seam` holds a single effect to
    one seam, so all-or-nothing reporting stays per consumer. The
    characteristic and armour seams are the two that honour a printed
    :class:`Bounded` amount — a ceiling on a characteristic, a floor (the
    best save) on the armour value.
    """

    ROLL = "roll"
    CHARACTERISTIC = "characteristic"
    RANK = "rank"
    COMBAT_RESULT = "combat-result"
    ARMOUR = "armour"
    WARD = "ward"


class Quantity(StrEnum):
    """A quantity a modifier can change, in the rulebook's own modifier vocabulary.

    The whole modifier vocabulary in one closed, append-only enum — a member
    joins when an imported rule needs it. Each member knows the :class:`Seam`
    that consumes it, so routing is the member's own knowledge, not a side
    table: ``to-hit`` and ``armour-piercing`` land on the dice walk,
    ``fighting-ranks`` / ``supporting-ranks`` on the fighting-rank query,
    ``combat-result`` on the combat-result fold, and ``armour-value`` on the
    armour fold (a defender improving its own save). A profile
    :class:`~avelorn.tow.schema.unit.Characteristic` is the one quantity kept
    apart — a stat vocabulary used far beyond modifiers — so an operation's
    key is a Quantity or a Characteristic.
    """

    TO_HIT = "to-hit"
    ARMOUR_PIERCING = "armour-piercing"
    FIGHTING_RANKS = "fighting-ranks"
    SUPPORTING_RANKS = "supporting-ranks"
    COMBAT_RESULT = "combat-result"
    ARMOUR_VALUE = "armour-value"
    WARD_SAVE = "ward-save"

    @property
    def seam(self) -> Seam:
        """The seam that consumes this quantity."""
        match self:
            case Quantity.TO_HIT | Quantity.ARMOUR_PIERCING:
                return Seam.ROLL
            case Quantity.FIGHTING_RANKS | Quantity.SUPPORTING_RANKS:
                return Seam.RANK
            case Quantity.COMBAT_RESULT:
                return Seam.COMBAT_RESULT
            case Quantity.ARMOUR_VALUE:
                return Seam.ARMOUR
            case Quantity.WARD_SAVE:
                return Seam.WARD
            case unhandled:
                assert_never(unhandled)


def seam_of(key: "Quantity | Characteristic") -> Seam:
    """The seam that consumes an operation's key.

    Returns:
        The quantity's own seam, or the characteristic seam for a profile
        characteristic (the quantity kept outside :class:`Quantity`).
    """
    return Seam.CHARACTERISTIC if isinstance(key, Characteristic) else key.seam
