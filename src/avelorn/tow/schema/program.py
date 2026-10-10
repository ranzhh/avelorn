"""Program file schema."""

from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.step import StepSequence


class FactType(StrEnum):
    """Value type."""

    INT = "int"
    BOOL = "bool"
    STANDING = "standing"
    USES = "uses"
    ARC = "arc"


class DerivedFact(StrEnum):
    """A printed quantity with no step of its own, worked out at the step that reads it."""

    RANK_BONUS = "rank-bonus"
    UNIT_STRENGTH = "unit-strength"


class Per(StrEnum):
    """A state fact's key."""

    SIDE = "side"


class Lifetime(StrEnum):
    """How long a state fact holds before it is cleared."""

    TURN = "turn"
    COMBAT = "combat"
    GAME = "game"


class StateFact(BaseModel):
    """A state fact."""

    model_config = ConfigDict(extra="forbid")

    fact: str
    type: FactType
    per: Per
    lasts: Lifetime


class StateFile(BaseModel):
    """State fact list."""

    model_config = ConfigDict(extra="forbid")

    facts: list[StateFact] = Field(min_length=1)


class FactInput(BaseModel):
    """A state fact input."""

    model_config = ConfigDict(extra="forbid")

    fact: str
    of: Side

    @property
    def name(self) -> str:
        """The fact's name, prefixed by its side."""
        return f"{self.of}/{self.fact}"


class KnownInput(BaseModel):
    """A known input."""

    model_config = ConfigDict(extra="forbid")

    known: str
    type: FactType
    of: Side | None = None

    @property
    def name(self) -> str:
        """The known's name, prefixed by its side when it has one."""
        return self.known if self.of is None else f"{self.of}/{self.known}"


def _distinct(sides: list[Side]) -> list[Side]:
    if len(set(sides)) < len(sides):
        raise ValueError("a side is listed twice")
    return sides


Sides = Annotated[list[Side], Field(min_length=1), AfterValidator(_distinct)]


class StepEntry(BaseModel):
    """One step of a program.

    ``of`` names the side it acts for, its printed side by default. A list of
    sides makes the step once for each, in order.
    """

    model_config = ConfigDict(extra="forbid")

    step: str
    of: Side | Sides | None = None
    sequence: StepSequence | None = None
    readings: list[str] = Field(default_factory=list)
    tallies: list[str] = Field(default_factory=list)

    @property
    def sides(self) -> tuple[Side | None, ...]:
        """Each side the step is made for, in order."""
        return tuple(self.of) if isinstance(self.of, list) else (self.of,)


class Each(StrEnum):
    """What a group of steps runs once for."""

    FIGHTER = "each-fighter"


class GroupEntry(BaseModel):
    """A group of steps run once for each fighter of a side, as many times as its share.

    A list of sides makes the group once for each, in order.
    """

    model_config = ConfigDict(extra="forbid")

    group: str
    for_: Each = Field(alias="for")
    of: Side | Sides
    times: str
    items: list[StepEntry | str] = Field(min_length=1)

    @property
    def sides(self) -> tuple[Side, ...]:
        """Each side the group is made for, in order."""
        return tuple(self.of) if isinstance(self.of, list) else (self.of,)


class Slots(StrEnum):
    """What a run of slots is numbered by."""

    INITIATIVE = "initiative"


class SlotsEntry(BaseModel):
    """A run of slots, each opening no scope, one for each value from ``from`` to ``to``.

    Each slot is named ``<slots>-<value>``, and its steps strike at that value.
    """

    model_config = ConfigDict(extra="forbid")

    slots: Slots
    from_: int = Field(alias="from", ge=1, le=10)
    to: int = Field(ge=1, le=10)
    items: list[GroupEntry | StepEntry | str] = Field(min_length=1)

    @property
    def values(self) -> range:
        """Each slot's value, from ``from`` to ``to`` inclusive."""
        step = -1 if self.to < self.from_ else 1
        return range(self.from_, self.to + step, step)


class SlotEntry(BaseModel):
    """A slot named after the step that opens it, its steps run with that step's own."""

    model_config = ConfigDict(extra="forbid")

    slot: str
    items: list[GroupEntry | StepEntry | str] = Field(min_length=1)


class ProgramFile(BaseModel):
    """A program file; ``fielded`` names the sides each build fields."""

    model_config = ConfigDict(extra="forbid")

    program: str
    sequence: StepSequence
    fielded: list[Side]
    inputs: list[FactInput | KnownInput]
    items: list[GroupEntry | SlotEntry | SlotsEntry | StepEntry | str] = Field(min_length=1)
