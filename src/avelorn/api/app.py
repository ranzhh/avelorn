"""The HTTP surface: the corpus under ``data/``, over the wire.

The same window the CLI opens, addressed by URL instead of by argument. It
reads the database — the datasheets and what they may take — and owns no
maths. What the engine *resolves* is not routed here: a volley, a round of
close combat, a break test, a question folded across two turns. Each is a
capability, and a request body per resolver signature is not a way to ask for
one; the vocabulary for posing them comes first (see the README's roadmap).

A datasheet is already a validated Pydantic model, so serving one is mostly a
matter of routing to it rather than describing it a second time in a shape that
could drift from the data. The one projection is
:class:`~avelorn.tow.views.UnitDetail`, which resolves the rule names a datasheet
prints to the entries they address, so a caller links to a rule instead of
deriving a slug from a printed name.
"""

from importlib.metadata import version
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from avelorn.tow.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.data import TOWRepository, default_repository
from avelorn.tow.game import TOWGame
from avelorn.tow.muster import Complement
from avelorn.tow.schema.rule import Rule
from avelorn.tow.views import (
    FightReport,
    MusteredUnit,
    RuleSummary,
    UnitDetail,
    UnitSummary,
    UnmodelledRule,
    rule_summaries,
    unmodelled_rules,
)

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


@app.get("/units", summary="List every datasheet in the corpus")
def list_units(data: Corpus) -> list[UnitSummary]:
    """List the datasheets, ordered by slug.

    Returns:
        One summary per unit.
    """
    return [UnitSummary.of(unit) for _, unit in sorted(data.units.items())]


@app.get("/units/{slug}", summary="Read one datasheet")
def read_unit(slug: str, data: Corpus) -> UnitDetail:
    """Read a datasheet in full: its profiles, equipment, rules, and options.

    Returns:
        The datasheet, its troop-type profile resolved and each printed rule
        name carrying the entry it resolves to.

    Raises:
        HTTPException: 404, when no datasheet carries the slug.
    """
    unit = data.units.get(slug)
    if unit is None:
        raise HTTPException(status_code=404, detail=f"no unit {slug!r}")
    return UnitDetail.of(unit, data.rules)


class Muster(BaseModel):
    """What a caller asks to field: a datasheet, a model count, and options by name."""

    model_config = ConfigDict(extra="forbid")

    unit: str
    size: int = Field(ge=1)
    options: list[str] = Field(default_factory=list)


@app.post("/muster", summary="Cost and equip one block of an army list")
def muster(request: Muster, data: Corpus) -> MusteredUnit:
    """Size and equip a datasheet, and derive what the block costs.

    Says nothing about whether a list of these is legal -- army composition
    is not modelled yet. This costs one block and refuses one the datasheet
    does not allow.

    Returns:
        The block, its points and effective loadout derived.

    Raises:
        HTTPException: 404, when no datasheet carries the slug; 422, when the
            datasheet does not allow the size or the options asked for.
    """
    unit = data.units.get(request.unit)
    if unit is None:
        raise HTTPException(status_code=404, detail=f"no unit {request.unit!r}")
    try:
        complement = Complement(unit=unit, size=request.size, options=request.options)
    except ValidationError as invalid:
        raise HTTPException(status_code=422, detail=_first_message(invalid)) from invalid
    return MusteredUnit.of(complement, data.rules)


def _first_message(invalid: ValidationError) -> str:
    # Complement raises one ValueError at a time, so the first error's message
    # is the whole reason. Pydantic prefixes it with "Value error, ".
    message = invalid.errors()[0]["msg"]
    return message.removeprefix("Value error, ")


class Deployment(BaseModel):
    """One side put on the table: a datasheet, sized and equipped, weapon in hand."""

    model_config = ConfigDict(extra="forbid")

    unit: str
    size: int = Field(ge=1)
    options: list[str] = Field(default_factory=list)
    # The weapon the side fights with, by printed name. A unit fights with what
    # it carries, and it must be one that can fight -- a bow has no Combat
    # profile. Omitted, it takes the last carried weapon that has one, which is
    # the specialist a datasheet prints after the hand weapon every model has.
    weapon: str | None = None
    frontage: int | None = Field(default=None, ge=1)


class ChargedBy(BaseModel):
    """A charge into the round: who made it, how far it carried, which arc it struck."""

    model_config = ConfigDict(extra="forbid")

    side: Literal["a", "b"]
    full_inches: int = Field(ge=0)
    arc: ChargeArc = ChargeArc.FRONT


class Fight(BaseModel):
    """Two sides meeting in close combat, and the charge that brought them together."""

    model_config = ConfigDict(extra="forbid")

    a: Deployment
    b: Deployment
    charge: ChargedBy | None = None


@app.post("/fight", summary="Resolve one round of close combat between two units")
def fight(request: Fight, data: Corpus) -> FightReport:
    """Deploy two units, fight one round, and score it.

    One round: both sides strike in Initiative order, the Wounds tally into a
    combat result, and the loser takes its Break test. What a round does not
    cover is the rest of the engagement — a pursuit, a second round, and the
    Stand & Shoot a charge would be met with, which needs the Movement phase's
    charge sequence rather than a charge recorded on the charger.

    A side the corpus cannot field is refused before any dice are walked: an
    unknown slug is a 404, and a size, option or weapon the datasheet does not
    allow is a 422 naming which side asked for it.

    Returns:
        The round resolved: each side's casualty distribution and Break-test
        outcomes, who won, and every rule the engine held without applying.
    """
    game = TOWGame.assemble(data)
    a = _deploy(game, data, request.a, "a")
    b = _deploy(game, data, request.b, "b")
    if request.charge is not None:
        charged = Charge(request.charge.full_inches, request.charge.arc)
        if request.charge.side == "a":
            a = a.charging(charged)
        else:
            b = b.charging(charged)
    fought = game.combat.fight(a, b)
    scored = game.combat.result(fought)
    return FightReport.of(a, b, fought, scored, game.combat.break_test(scored, a, b))


def _deploy(game: TOWGame, data: TOWRepository, side: Deployment, label: str) -> Contingent:
    # The muster boundary for one side of a fight: every refusal a datasheet
    # makes -- the size, the options, the weapon it does not carry -- becomes a
    # 422 naming which side asked for it.
    if side.unit not in game.units:
        raise HTTPException(status_code=404, detail=f"no unit {side.unit!r}")
    try:
        fielded = Contingent.deploy(
            side.unit, side.size, side.options, data=data, frontage=side.frontage
        )
        armed = fielded.wielding(side.weapon or _default_weapon(fielded, label))
    except (ValidationError, ValueError) as refused:
        raise HTTPException(
            status_code=422, detail=f"side {label}: {_reason(refused)}"
        ) from refused
    # A round of close combat is the only thing routed here, so a weapon that
    # cannot fight is a refusal at the boundary rather than a resolver blowing
    # up mid-walk.
    if armed.in_hand().combat_profile is None:
        raise HTTPException(
            status_code=422,
            detail=f"side {label}: {armed.in_hand().name} has no Combat profile; it cannot fight",
        )
    return armed


def _default_weapon(fielded: Contingent, label: str) -> str:
    # The last carried weapon that can fight: a datasheet prints the specialist
    # after the hand weapon, and a missile weapon after both, so taking the last
    # outright sends archers into melee with a bow.
    for weapon in reversed(fielded.loadout.weapons):
        if weapon.combat_profile is not None:
            return weapon.name
    carried = ", ".join(weapon.name for weapon in fielded.loadout.weapons) or "nothing"
    raise HTTPException(
        status_code=422,
        detail=f"side {label}: nothing it carries can fight in close combat; carried: {carried}",
    )


def _reason(refused: ValidationError | ValueError) -> str:
    # Complement raises through Pydantic, a loadout raises a bare ValueError.
    if isinstance(refused, ValidationError):
        return refused.errors()[0]["msg"].removeprefix("Value error, ")
    return str(refused)


@app.get("/rules", summary="List every rule entry in the corpus")
def list_rules(data: Corpus) -> list[RuleSummary]:
    """List the rule entries, ordered by slug.

    Returns:
        One summary per entry.
    """
    return rule_summaries(data)


# Declared before /rules/{slug}, so the path matches this route rather than
# being read as a slug. No rule is filed under "unmodelled", and none can be
# while this route owns the name.
@app.get("/rules/unmodelled", summary="Report the printed rules the engine does not apply")
def list_unmodelled(data: Corpus) -> list[UnmodelledRule]:
    """Report every rule the corpus prints that never reaches the maths.

    Returns:
        The report, most-printed first.
    """
    return unmodelled_rules(data)


@app.get("/rules/{slug}", summary="Read one rule entry")
def read_rule(slug: str, data: Corpus) -> Rule:
    """Read a rule entry in full: its text, its effects, and what it leaves out.

    Returns:
        The rule entry.

    Raises:
        HTTPException: 404, when no entry carries the slug. A rule the corpus
            prints without an entry has none to read; ``/rules/unmodelled``
            names those.
    """
    rule = data.rules.get(slug)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"no rule entry {slug!r}")
    return rule
