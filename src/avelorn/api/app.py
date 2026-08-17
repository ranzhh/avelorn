"""The HTTP surface: the corpus under ``data/``, over the wire.

The same window the CLI opens, addressed by URL instead of by argument. It
reads the database — the datasheets and what they may take — and owns no
maths. What the engine *resolves* is not routed here: a volley, a round of
close combat, a break test, a question folded across two turns. Each is a
capability, and a request body per resolver signature is not a way to ask for
one; the vocabulary for posing them comes first (see the README's roadmap).

A datasheet is already a validated Pydantic model, so serving one is a matter
of routing to it rather than describing it a second time in a shape that could
drift from the data.
"""

from importlib.metadata import version
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from avelorn.tow.data import TOWRepository, default_repository
from avelorn.tow.schema.unit import TroopType, Unit, UnitSize

app = FastAPI(
    title="Avelorn",
    version=version("avelorn"),
    summary="The unit and army database for Warhammer: The Old World.",
)


def corpus() -> TOWRepository:
    """The game data every request reads.

    The process-wide default repository, which loads each registry once and
    reuses it, so a request pays for the YAML tree only if it is the first to
    need that part of it. Overridden in tests to serve a doctored corpus.

    Returns:
        The repository.
    """
    return default_repository()


Corpus = Annotated[TOWRepository, Depends(corpus)]


class UnitSummary(BaseModel):
    """A datasheet as the listing shows it: what it costs and how it is fielded.

    Deliberately not the whole datasheet. Profiles, equipment, rules, and
    options are what ``GET /units/{slug}`` is for; serving them for every unit
    at once makes the listing grow with the corpus rather than with its length.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    points: int
    unit_size: UnitSize
    troop_type: TroopType


@app.get("/units", summary="List every datasheet in the corpus")
def list_units(data: Corpus) -> list[UnitSummary]:
    """List the datasheets, ordered by slug.

    Returns:
        One summary per unit.
    """
    return [
        UnitSummary.model_validate(unit, from_attributes=True)
        for _, unit in sorted(data.units.items())
    ]


@app.get("/units/{slug}", summary="Read one datasheet")
def read_unit(slug: str, data: Corpus) -> Unit:
    """Read a datasheet in full: its profiles, equipment, rules, and options.

    Returns:
        The datasheet, its troop-type profile resolved.

    Raises:
        HTTPException: 404, when no datasheet carries the slug.
    """
    unit = data.units.get(slug)
    if unit is None:
        raise HTTPException(status_code=404, detail=f"no unit {slug!r}")
    return unit
