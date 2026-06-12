"""Missile weapon profiles, as printed in the rulebook.

Only profiles verified against tow.whfb.app belong here; equipment names
on units are plain strings, so callers map them to these profiles
explicitly. Sources: weapons-of-war/longbow, weapons-of-war/warbow.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MissileWeapon:
    """A ranged weapon profile: range, Strength, AP, and special rules."""

    name: str
    range_inches: int
    strength: int | None  # printed "S" = None: shots use the wielder's Strength
    armour_piercing: int = 0  # printed convention: 0 = "-", negative worsens saves
    special_rules: tuple[str, ...] = ()


LONGBOW = MissileWeapon(name="Longbow", range_inches=30, strength=3)
WARBOW = MissileWeapon(name="Warbow", range_inches=24, strength=None)
