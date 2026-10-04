"""Program file schema."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.step import StepSequence


class FactType(StrEnum):
    """Value type."""

    INT = "int"
    BOOL = "bool"
    STANDING = "standing"


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


class StepEntry(BaseModel):
    """One step of a program."""

    model_config = ConfigDict(extra="forbid")

    step: str
    sequence: StepSequence | None = None
    readings: list[str] = Field(default_factory=list)
    tallies: list[str] = Field(default_factory=list)


class GroupEntry(BaseModel):
    """A repeated group of steps."""

    model_config = ConfigDict(extra="forbid")

    group: str
    times: str
    items: list[StepEntry | str] = Field(min_length=1)


class ProgramFile(BaseModel):
    """A program file; ``fielded`` names the sides each build fields."""

    model_config = ConfigDict(extra="forbid")

    program: str
    sequence: StepSequence
    fielded: list[Side]
    inputs: list[FactInput | KnownInput]
    items: list[GroupEntry | StepEntry | str] = Field(min_length=1)
