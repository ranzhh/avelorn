"""Determining Armour Value: fold the worn armour into a save value.

The printed "Determining Armour Value" step (the-shooting-phase); the
close-combat step "Determining Armour Saves (Combat)" defers to it. A
model's worn armour resolves to a single value — the best suit worn,
improved by stacking bonuses (a shield's +1) — which
:func:`~avelorn.tow.combat.charts.armour_save_target` then turns into a
save roll after the weapon's Armour Piercing. Phase-neutral: both
shooting and close combat resolve the defender's save this way.

The armour comes off the defender's resolved
:class:`~avelorn.tow.contingent.Loadout`: name resolution
happened at the muster boundary, so there is nothing left to miss here
— no registry threaded in, no "equipment not factored" note out.
"""

from avelorn.tow.combat.charts import BEST_ARMOUR_VALUE, UNARMOURED
from avelorn.tow.contingent import Loadout


def defender_armour(loadout: Loadout) -> int | None:
    """Fold a defender's worn armour into its armour value.

    Returns:
        The armour value: the best suit worn improved by every stacking
        bonus, floored at 2+ — or None when the model is effectively
        unarmoured.
    """
    suit = UNARMOURED
    improvement = 0
    for armour in loadout.armour:
        if armour.armour_value is not None:
            suit = min(suit, armour.armour_value)
        elif armour.armour_value_improvement is not None:
            improvement += armour.armour_value_improvement
    value = max(suit - improvement, BEST_ARMOUR_VALUE)
    return value if value < UNARMOURED else None
