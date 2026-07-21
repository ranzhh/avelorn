"""Unit Strength: a model's contribution to its unit's fighting mass.

The troop-type table (troop-types-at-a-glance/troop-type-table) prints a
per-model Unit Strength for each troop type: a fixed count for most —
Regular and Heavy Infantry 1, cavalry 2, Monstrous Infantry and Swarms 3,
a Heavy Chariot 5 — or the printed "As Starting Wounds" for the troop
types whose strength scales with the model itself: Monstrous Creatures,
Behemoths, and War Machines. A unit's Unit Strength is the sum of its
models', so it is settled by the troop type and the model count, deciding
which side outnumbers the other for the combat-result bonus, panic, and
the like.

The value lives on each troop type's data (``TroopTypeProfile``), and the
troop type resolves it against a model's Wounds — the one place a marker
like "W" is read.
"""

from enum import StrEnum


class UnitStrengthMarker(StrEnum):
    """The troop-type table's non-numeric Unit Strength markers.

    A closed, append-only vocabulary like the rulebook's other tables: a
    member joins when the Unit Strength column prints a new marker in place
    of a number. ``STARTING_WOUNDS`` is the table's "W" — the model's Unit
    Strength is its starting Wounds, not a fixed count. Each marker names a
    distinct resolution, so the troop type must match on the member rather
    than lump every non-numeric value together.
    """

    STARTING_WOUNDS = "W"


# A troop type's per-model Unit Strength as the table prints it: a fixed
# count, or a marker resolved against the model (STARTING_WOUNDS -> Wounds).
type UnitStrength = int | UnitStrengthMarker
