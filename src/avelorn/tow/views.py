"""What a caller shows of a unit: the views both surfaces present.

The command line and the HTTP API are windows on the same corpus, and a unit
must look the same through either. How they render differs -- aligned columns
against JSON -- but *what is carried* is declared once, here, so neither can
quietly fall behind the other.

Two views, because there are two questions. A listing answers "what is in the
corpus, and what does it cost": :class:`UnitSummary`, deliberately not the whole
datasheet, since serving every unit's profiles and options at once makes a
listing grow with the corpus rather than with its length. Reading one datasheet
answers everything else, and its view is the schema type itself
(:class:`~avelorn.tow.schema.unit.Unit`) -- there is nothing to project, so
projecting it would only create something to drift.
"""

from pydantic import BaseModel, ConfigDict

from avelorn.tow.schema.unit import TroopType, Unit, UnitSize


class UnitSummary(BaseModel):
    """A datasheet as a listing shows it: what it costs and how it is fielded."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    points: int
    unit_size: UnitSize
    troop_type: TroopType

    @classmethod
    def of(cls, unit: Unit) -> "UnitSummary":
        """Summarise one datasheet.

        Returns:
            The listing view of ``unit``.
        """
        return cls.model_validate(unit, from_attributes=True)
