"""Psychology vocabularies: the printed causes of panic.

The Psychology of War chapter names exactly four causes, each its own
section (tow.whfb.app/the-psychology-of-war): Heavy Casualties, Nearby
Friend Destroyed, Nearby Friend Flees Combat, Fled Through. Effects
that touch panic tests filter on them.
"""

from enum import StrEnum


class PanicCause(StrEnum):
    """Why a panic test was forced, named as the sections are printed."""

    HEAVY_CASUALTIES = "heavy-casualties"
    NEARBY_FRIEND_DESTROYED = "nearby-friend-destroyed"
    NEARBY_FRIEND_FLEES_COMBAT = "nearby-friend-flees-combat"
    FLED_THROUGH = "fled-through"
