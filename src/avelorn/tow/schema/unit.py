"""Unit models for Warhammer: The Old World.

Field aliases mirror the rulebook profile headers (M, WS, BS, ...) so
hand-authored YAML reads like the printed stat line; Python code uses the
long names.
"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.functional_validators import BeforeValidator


def _dash_to_none(value: object) -> object:
    if value == "-":
        return None
    return value


# A profile characteristic; "-" in source material means not applicable.
Stat = Annotated[int | None, BeforeValidator(_dash_to_none)]


class Profile(BaseModel):
    """One row of a characteristic profile.

    A unit may have several, e.g. rank-and-file plus champion.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    movement: Stat = Field(alias="M")
    weapon_skill: Stat = Field(alias="WS")
    ballistic_skill: Stat = Field(alias="BS")
    strength: Stat = Field(alias="S")
    toughness: Stat = Field(alias="T")
    wounds: Stat = Field(alias="W")
    initiative: Stat = Field(alias="I")
    attacks: Stat = Field(alias="A")
    leadership: Stat = Field(alias="Ld")


class UnitSize(BaseModel):
    """Allowed model count for a unit."""

    model_config = ConfigDict(extra="forbid")

    min: int = Field(ge=1)
    max: int | None = Field(default=None, ge=1)  # None = no upper limit

    @model_validator(mode="after")
    def _max_not_below_min(self) -> Self:
        if self.max is not None and self.max < self.min:
            raise ValueError(f"max ({self.max}) must be >= min ({self.min})")
        return self


class BaseSize(BaseModel):
    """Base footprint of a single model, in millimetres."""

    model_config = ConfigDict(extra="forbid")

    width_mm: int = Field(ge=1)
    depth_mm: int = Field(ge=1)


class TroopType(StrEnum):
    """Closed set from the rulebook's troop-type table."""

    REGULAR_INFANTRY = "Regular Infantry"
    HEAVY_INFANTRY = "Heavy Infantry"
    MONSTROUS_INFANTRY = "Monstrous Infantry"
    SWARM = "Swarm"
    LIGHT_CAVALRY = "Light Cavalry"
    HEAVY_CAVALRY = "Heavy Cavalry"
    MONSTROUS_CAVALRY = "Monstrous Cavalry"
    WAR_BEAST = "War Beast"
    LIGHT_CHARIOT = "Light Chariot"
    HEAVY_CHARIOT = "Heavy Chariot"
    MONSTROUS_CREATURE = "Monstrous Creature"
    BEHEMOTH = "Behemoth"
    WAR_MACHINE = "War Machine"


class OptionKind(StrEnum):
    """Coarse category of a unit option."""

    CHAMPION = "champion"
    STANDARD_BEARER = "standard_bearer"
    MUSICIAN = "musician"
    EQUIPMENT = "equipment"
    SPECIAL_RULE = "special_rule"
    MAGIC_STANDARD = "magic_standard"
    OTHER = "other"


class UnitOption(BaseModel):
    """A purchasable upgrade.

    Exactly one cost shape applies: a flat `points` cost (per unit, or per
    model when `per_model` is set) or a `points_budget` to spend up to
    (e.g. magic standards).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: OptionKind = OptionKind.OTHER
    points: int | None = Field(default=None, ge=0)
    per_model: bool = False
    points_budget: int | None = Field(default=None, ge=1)
    adds_rules: list[str] = Field(default_factory=list)
    removes_rules: list[str] = Field(default_factory=list)
    adds_equipment: list[str] = Field(default_factory=list)
    removes_equipment: list[str] = Field(default_factory=list)
    # Availability restriction, free text for now (e.g. "0-1 unit per
    # 1000 points"); becomes structured when the validation engine needs it.
    limit: str | None = None

    # Interim guard until cost shapes become a discriminated union.
    @model_validator(mode="after")
    def _exactly_one_cost_shape(self) -> Self:
        if (self.points is None) == (self.points_budget is None):
            raise ValueError("exactly one of points or points_budget must be set")
        if self.per_model and self.points is None:
            raise ValueError("per_model applies to points, not points_budget")
        return self


class Unit(BaseModel):
    """A unit entry as printed in an army's list."""

    model_config = ConfigDict(extra="forbid")

    id: str  # stable slug, e.g. "elven-spearmen"
    name: str
    points: int = Field(ge=0)  # per model
    unit_size: UnitSize
    troop_type: TroopType
    base_size: BaseSize | None = None
    profiles: list[Profile] = Field(min_length=1)
    equipment: list[str] = Field(default_factory=list)
    special_rules: list[str] = Field(default_factory=list)  # rule names, as printed
    options: list[UnitOption] = Field(default_factory=list)
