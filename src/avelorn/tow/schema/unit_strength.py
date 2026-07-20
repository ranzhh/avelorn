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
troop type resolves it against a model's Wounds — the one place the "As
Starting Wounds" cell is read.
"""

from typing import Literal

# The troop-type table's "As Starting Wounds" cell: a model's Unit Strength
# is the Wounds on its profile, not a fixed count.
AS_STARTING_WOUNDS = "as-starting-wounds"

# A troop type's per-model Unit Strength as the table prints it: a fixed
# count, or the "As Starting Wounds" marker resolved against the model.
type UnitStrength = int | Literal["as-starting-wounds"]
