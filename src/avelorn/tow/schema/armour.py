"""Armour models for Warhammer: The Old World.

Armour entries have no weapon-style profile in the rulebook: a suit
confers an armour value ("Armour Value: 6+"), an addition such as a
shield improves the wearer's armour value by a fixed amount.
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Armour(BaseModel):
    """An armour entry: a suit with its own value, or an addition."""

    model_config = ConfigDict(extra="forbid")

    id: str  # stable slug, e.g. "light-armour"
    name: str
    armour_value: int | None = Field(default=None, ge=1, le=6)  # printed "6+" -> 6
    armour_value_improvement: int | None = Field(default=None, ge=1)
    notes: str | None = None  # printed usage restrictions, verbatim

    @model_validator(mode="after")
    def _exactly_one_shape(self) -> Self:
        if (self.armour_value is None) == (self.armour_value_improvement is None):
            raise ValueError("exactly one of armour_value or armour_value_improvement must be set")
        return self
