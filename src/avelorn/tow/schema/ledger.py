"""The coverage ledger: the gaps between the corpus and the engine, each acknowledged.

``data/tow/unmodelled.yaml`` lists what the corpus prints and the engine does
not read, one entry per gap with the reason it stays open. The coverage report
(:mod:`avelorn.tow.coverage`) matches these against the gaps it finds.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class GapKind(StrEnum):
    """How a piece of the corpus fails to reach the maths."""

    RULE_WITHOUT_ENTRY = "rule-without-entry"
    PARAMETER_UNBOUND = "parameter-unbound"
    PROFILE_ROW_UNREAD = "profile-row-unread"
    PRINTED_NOTES = "printed-notes"
    INERT_OPTION = "inert-option"


class Acknowledgement(BaseModel):
    """One gap, known and left open, with why.

    ``subject`` is how the gap is addressed: the printed rule name for the rule
    kinds (one entry covers every place printing it), ``<unit>/<row>`` for a
    profile row, the weapon or armour slug for printed notes, and
    ``<unit>/<option>`` for an option.
    """

    model_config = ConfigDict(extra="forbid")

    kind: GapKind
    subject: str
    reason: str = Field(min_length=1)
    issue: int | None = Field(default=None, ge=1)


class Ledger(RootModel[list[Acknowledgement]]):
    """Every acknowledged gap, each acknowledged once."""

    @model_validator(mode="after")
    def _one_entry_per_gap(self) -> Self:
        keys = [(entry.kind, entry.subject) for entry in self.root]
        repeated = sorted(
            {f"{kind}: {subject}" for kind, subject in keys if keys.count((kind, subject)) > 1}
        )
        if repeated:
            raise ValueError(f"gaps acknowledged more than once: {repeated}")
        return self
