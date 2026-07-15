"""Determining Armour Value: fold the worn armour into a save value.

The printed "Determining Armour Value" step (the-shooting-phase); the
close-combat step "Determining Armour Saves (Combat)" defers to it. A
model's worn armour resolves to a single value — the best suit worn,
improved by stacking bonuses (a shield's +1) — which
:func:`~avelorn.tow.engine.charts.armour_save_target` then turns into a
save roll after the weapon's Armour Piercing. Phase-neutral: both
shooting and close combat resolve the defender's save this way.

The ``worn`` armour comes off the defender's resolved
:class:`~avelorn.tow.contingent.Loadout` (its ``armour``): name resolution
happened at the muster boundary, so there is nothing left to miss here
— no registry threaded in, no "equipment not factored" note out. Taking the
armour pieces rather than the whole loadout keeps this pure engine math, with
no dependency on the on-field :class:`~avelorn.tow.contingent.Contingent`.
"""

from collections.abc import Sequence

from avelorn.tow.engine.charts import BEST_ARMOUR_VALUE, UNARMOURED
from avelorn.tow.schema.armour import Armour


def defender_armour(worn: Sequence[Armour]) -> int | None:
    """Fold a defender's worn armour into its armour value.

    Args:
        worn: The armour pieces the defender wears (a loadout's ``armour``).

    Returns:
        The armour value: the best suit worn improved by every stacking
        bonus, floored at 2+ — or None when the model is effectively
        unarmoured.
    """
    suit = UNARMOURED
    improvement = 0
    for piece in worn:
        if piece.armour_value is not None:
            suit = min(suit, piece.armour_value)
        elif piece.armour_value_improvement is not None:
            improvement += piece.armour_value_improvement
    value = max(suit - improvement, BEST_ARMOUR_VALUE)
    return value if value < UNARMOURED else None
