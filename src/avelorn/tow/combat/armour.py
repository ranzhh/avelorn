"""Determining Armour Value: resolve worn equipment into a save value.

The printed "Determining Armour Value" step (the-shooting-phase); the
close-combat step "Determining Armour Saves (Combat)" defers to it. A
model's worn armour resolves to a single value — the best suit worn,
improved by stacking bonuses (a shield's +1) — which
:func:`~avelorn.tow.combat.charts.armour_save_target` then turns into a
save roll after the weapon's Armour Piercing. Phase-neutral: both
shooting and close combat resolve the defender's save this way.
"""

from collections.abc import Mapping

from avelorn.tow.combat.charts import BEST_ARMOUR_VALUE, UNARMOURED
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.unit import Unit

# NOTE: the (unit + registry) -> (value, notes) shape here is a known wart.
# A positional tuple return, and a string-keyed registry threaded in by the
# caller, degrade as more such resolvers accrue (rules, weapons, ...). It is
# kept deliberately for now, shared by both phases; the intended replacement
# is a Repository that holds the registries and offers resolution helpers, so
# a caller asks an object rather than splicing tuples of values and notes.


def defender_armour(defender: Unit, armoury: Mapping[str, Armour]) -> tuple[int | None, list[str]]:
    """Resolve a defending unit's armour value from its worn equipment.

    ``armoury`` maps printed equipment names to armour items; equipment
    it does not resolve is reported in the returned notes rather than
    silently ignored.

    Returns:
        The armour value (or None when the model is effectively
        unarmoured), and notes for any equipment not factored in.
    """
    suit = UNARMOURED
    improvement = 0
    notes: list[str] = []
    for item in defender.equipment:
        armour = armoury.get(item)
        if armour is None:
            notes.append(f"equipment not factored: {item} ({defender.name})")
        elif armour.armour_value is not None:
            suit = min(suit, armour.armour_value)
        elif armour.armour_value_improvement is not None:
            improvement += armour.armour_value_improvement
    value = max(suit - improvement, BEST_ARMOUR_VALUE)
    return (value if value < UNARMOURED else None), notes
