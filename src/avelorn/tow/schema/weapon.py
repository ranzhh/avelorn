"""Weapon models for Warhammer: The Old World.

Field aliases mirror the printed weapon chart headers (R, S, AP) so the
hand-authored YAML reads like the rulebook table; Python code uses the
long names. Printed conventions are parsed, not stored as strings: a
Strength of "S+2" becomes a wielder-relative value, an Armour Piercing
of "-" becomes 0.
"""

import re
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.functional_validators import BeforeValidator

_RELATIVE_STRENGTH_RE = re.compile(r"S([+-]\d+)?")


class WeaponType(StrEnum):
    """A weapon's family in the Weapons of War chapter — a closed, append-only set.

    The rulebook groups weapons into families a rule can speak to as one ("any
    bow" — a longbow, shortbow, warbow or the Bow of Avelorn). The source does
    not carry the family as a field, and the individual weapon entries do not
    name it, so it is hand-authored here. A member joins, and a weapon is
    classified, only when a rule needs to gate on the family — the same
    just-in-time discipline the rest of the vocabulary follows. Values are the
    family as the rulebook names it.
    """

    BOW = "Bow"


class WeaponStrength(BaseModel):
    """A weapon profile's Strength, as printed.

    Absolute ("4"), or relative to the wielder's own Strength ("S",
    "S+2").
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    base: int | None = Field(default=None, ge=1)  # absolute; None = relative
    modifier: int = 0  # offset on the wielder's Strength when relative

    @model_validator(mode="before")
    @classmethod
    def _parse_printed(cls, value: object) -> object:
        if isinstance(value, int):
            return {"base": value}
        if isinstance(value, str):
            text = value.strip()
            if m := _RELATIVE_STRENGTH_RE.fullmatch(text):
                return {"modifier": int(m.group(1) or 0)}
            if text.isdigit():
                return {"base": int(text)}
            raise ValueError(f"cannot parse weapon Strength {value!r}")
        return value

    @model_validator(mode="after")
    def _absolute_takes_no_modifier(self) -> Self:
        if self.base is not None and self.modifier != 0:
            raise ValueError("an absolute Strength cannot carry a modifier")
        return self

    def resolve(self, wielder_strength: int) -> int:
        """Compute the effective Strength for a given wielder.

        Returns:
            The absolute base, or the wielder's Strength plus the modifier.
        """
        if self.base is not None:
            return self.base
        return wielder_strength + self.modifier

    @property
    def is_relative(self) -> bool:
        """Whether this Strength depends on the wielder."""
        return self.base is None

    @property
    def printed(self) -> str:
        """The rulebook spelling: "4", "S" or "S+2"."""
        if self.base is not None:
            return str(self.base)
        return f"S{self.modifier:+d}" if self.modifier else "S"


def _dash_to_zero(value: object) -> object:
    if value == "-":
        return 0
    return value


# Printed convention: "-" means no armour piercing; negatives worsen saves.
ArmourPiercing = Annotated[int, BeforeValidator(_dash_to_zero), Field(le=0)]

# "Combat" for close quarters, otherwise a range in inches. Printed
# min-max bands (e.g. stone throwers' 12"-60") get modeled when the
# first such weapon is imported.
WeaponRange = Literal["Combat"] | Annotated[int, Field(gt=0)]


class WeaponProfile(BaseModel):
    """One printed profile row of a weapon.

    Most weapons have exactly one; some have several (e.g. a Brace of
    Pistols has a Ranged and a Combat row), distinguished by name.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str | None = None
    range: WeaponRange = Field(alias="R")
    strength: WeaponStrength = Field(alias="S")
    armour_piercing: ArmourPiercing = Field(alias="AP", default=0)
    special_rules: list[str] = Field(default_factory=list)  # rule names, as printed

    @property
    def is_missile(self) -> bool:
        """Whether this row describes a ranged attack."""
        return self.range != "Combat"


class Weapon(BaseModel):
    """A weapon entry as printed in the Weapons of War chapter."""

    model_config = ConfigDict(extra="forbid")

    id: str  # stable slug, e.g. "thrusting-spear"
    name: str
    weapon_type: WeaponType | None = None  # the rulebook family; None until a rule needs it
    profiles: list[WeaponProfile] = Field(min_length=1)
    notes: str | None = None  # printed usage restrictions, verbatim

    @property
    def missile_profile(self) -> WeaponProfile | None:
        """The weapon's ranged profile.

        Returns:
            The first non-Combat profile, or None for pure melee weapons.
        """
        return next((p for p in self.profiles if p.is_missile), None)

    @property
    def combat_profile(self) -> WeaponProfile | None:
        """The weapon's close-combat profile.

        Returns:
            The first Combat profile, or None for a pure missile weapon.
        """
        return next((p for p in self.profiles if not p.is_missile), None)
