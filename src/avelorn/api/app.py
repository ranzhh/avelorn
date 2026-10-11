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

from collections.abc import Callable, Mapping
from importlib.metadata import version
from typing import Annotated, Literal, NamedTuple

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from avelorn.tow.charge import ChargeRoll
from avelorn.tow.contingent import Charge, ChargeArc, Contingent, Movement
from avelorn.tow.coverage import Coverage, coverage
from avelorn.tow.data import TOWRepository, default_repository
from avelorn.tow.game import TOWGame
from avelorn.tow.lanes import FightLanes
from avelorn.tow.muster import Complement
from avelorn.tow.phases.movement import HOLD, ChargeReaction, StandAndShoot
from avelorn.tow.round import Fight as Round
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.side import Side
from avelorn.tow.schema.weapon import Weapon
from avelorn.tow.views import (
    FightReport,
    MusteredUnit,
    Reacting,
    RuleSummary,
    UnitDetail,
    UnitSummary,
    VolleyReport,
    WeaponDetail,
    WeaponSummary,
    rule_summaries,
)
from avelorn.tow.volley import Volley as Fired

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
    return [
        UnitSummary.of(unit, data.fielded_by[slug]) for slug, unit in sorted(data.units.items())
    ]


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
    return UnitDetail.of(unit, data)


class Muster(BaseModel):
    """What a caller asks to field: a datasheet, a model count, and options by id."""

    model_config = ConfigDict(extra="forbid")

    unit: str
    size: int = Field(ge=1)
    options: list[str] = Field(default_factory=list)
    # The formation width in files. Omitted, the troop type's default; a caller
    # re-forming a block on a table asks for the width it dragged it to.
    frontage: int | None = Field(default=None, ge=1)


@app.post("/muster", summary="Cost and equip one block of an army list")
def muster(request: Muster, data: Corpus) -> MusteredUnit:
    """Size and equip a datasheet, and derive what the block costs.

    Says nothing about whether a list of these is legal -- army composition
    is not modelled yet. This costs one block and refuses one the datasheet
    does not allow. A ``frontage`` re-forms the block that many models wide,
    which changes the footprint it stands on and nothing about its cost.

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
        return MusteredUnit.of(complement, data.rules, frontage=request.frontage)
    except ValidationError as invalid:
        raise HTTPException(status_code=422, detail=_first_message(invalid)) from invalid
    except ValueError as refused:
        raise HTTPException(status_code=422, detail=str(refused)) from refused


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
    """A charge into the round: who made it, the inches to the enemy, which arc it struck.

    ``reaction`` is how the charged side met it: a Hold, or a Stand & Shoot
    fired with the last missile weapon it carries.
    """

    model_config = ConfigDict(extra="forbid")

    side: Literal["a", "b"]
    full_inches: int = Field(ge=0)
    arc: ChargeArc = ChargeArc.FRONT
    reaction: Reacting = "hold"


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
    combat result, and the loser takes its Break test. A charge is met with
    the reaction its target declares: a Stand & Shoot fires before the round
    and thins the charger, and its Wounds count toward the target's combat
    result. ``p_charge_reaches`` is the chance the Charge roll reaches the
    target; the round is fought only when it does, so every figure of the
    round is conditional on the charge reaching. What a round does not cover
    is the rest of the engagement -- a pursuit, a second round.

    A side the corpus cannot field is refused before any dice are walked: an
    unknown slug is a 404, and a size, option or weapon the datasheet does not
    allow is a 422 naming which side asked for it, as is a Stand & Shoot by a
    side that carries no missile weapon.

    Returns:
        The round resolved: the chance the charge reaches, each side's
        casualty distribution and Break-test outcomes, who won, and every rule
        the engine held without applying.
    """
    engaged = _fought(request, data)
    seat = engaged.seat
    return FightReport.of(
        engaged.sides[seat], engaged.sides[seat.other], engaged.fight, seat, engaged.rolled
    )


@app.post("/graph/fight", summary="Draw the round a fight resolves in two lanes")
def graph_fight(request: Fight, data: Corpus) -> FightLanes:
    """Fight the round ``/fight`` fights, and draw it in a lane for each side.

    The charger takes the attacker's lane, above its target's; with no charge,
    side a does. ``charge.reaches`` is the chance the Charge roll reaches the
    target, ``full_inches`` away. The Stand & Shoot is fired before the roll,
    whatever it gives; the round is fought only when the charge reaches, so
    every figure from the strikes on is conditional on the charge reaching.

    Returns:
        The lanes, read off the lane ``/fight`` reports on.
    """
    engaged = _fought(request, data)
    return FightLanes.of(engaged.sides, engaged.fight, engaged.rolled, engaged.stood)


class _Engaged(NamedTuple):
    """Two sides in the seats a round puts them in, the charger the attacker.

    ``seat`` is the seat side a fights from, ``rolled`` the charge's Charge
    roll, and ``stood`` the Stand & Shoot the target met the charge with.
    """

    seat: Side
    sides: Mapping[Side, Contingent]
    fight: Round
    rolled: ChargeRoll | None
    stood: Fired | None


def _fought(request: Fight, data: TOWRepository) -> _Engaged:
    game = TOWGame.assemble(data)
    a = _deploy(game, data, request.a, "side a")
    b = _deploy(game, data, request.b, "side b")
    charge = request.charge
    if charge is None:
        sides = {Side.ATTACKER: a, Side.TARGET: b}
        return _Engaged(Side.ATTACKER, sides, game.combat.fight(a, b), None, None)
    seat, charger, target, label = (
        (Side.ATTACKER, a, b, "side b") if charge.side == "a" else (Side.TARGET, b, a, "side a")
    )
    engagement = game.movement.charge(charger, target, Charge(charge.full_inches, charge.arc))
    stood = engagement.react(_reaction(charge.reaction, target, label))
    sides = {Side.ATTACKER: engagement.a, Side.TARGET: engagement.b}
    return _Engaged(seat, sides, game.combat.fight(engagement), engagement.rolled, stood)


def _reaction(declared: Reacting, target: Contingent, label: str) -> ChargeReaction:
    if declared == "hold":
        return HOLD
    return StandAndShoot(_default_weapon(target, label, MISSILE))


class _Wields(NamedTuple):
    """What a phase needs of the weapon it puts in a unit's hand."""

    # Reads the profile off a weapon entry; None means it cannot serve here.
    profile: Callable[[Weapon], object | None]
    missing: str


MELEE = _Wields(lambda weapon: weapon.combat_profile, "Combat")
MISSILE = _Wields(lambda weapon: weapon.missile_profile, "missile")


def _deploy(
    game: TOWGame,
    data: TOWRepository,
    side: Deployment,
    label: str,
    wields: _Wields = MELEE,
) -> Contingent:
    # The muster boundary for one side of a fight: every refusal a datasheet
    # makes -- the size, the options, the weapon it does not carry -- becomes a
    # 422 naming which side asked for it.
    if side.unit not in game.units:
        raise HTTPException(status_code=404, detail=f"no unit {side.unit!r}")
    try:
        fielded = Contingent.deploy(
            side.unit, side.size, side.options, data=data, frontage=side.frontage
        )
        armed = fielded.wielding(side.weapon or _default_weapon(fielded, label, wields))
    except (ValidationError, ValueError) as refused:
        raise HTTPException(status_code=422, detail=f"{label}: {_reason(refused)}") from refused
    # The phase decides what a usable weapon is, so a weapon that cannot serve
    # is a refusal at the boundary rather than a resolver blowing up mid-walk.
    if wields.profile(armed.in_hand()) is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{label}: {armed.in_hand().name} has no {wields.missing} profile; "
                f"it cannot be used here"
            ),
        )
    return armed


def _default_weapon(fielded: Contingent, label: str, wields: _Wields) -> str:
    # The last carried weapon the phase can use: a datasheet prints the
    # specialist after the hand weapon and the missile weapon after both, so
    # taking the last outright sends archers into melee with a bow.
    for weapon in reversed(fielded.loadout.weapons):
        if wields.profile(weapon) is not None:
            return weapon.name
    carried = ", ".join(weapon.name for weapon in fielded.loadout.weapons) or "nothing"
    raise HTTPException(
        status_code=422,
        detail=(f"{label}: nothing it carries has a {wields.missing} profile; carried: {carried}"),
    )


def _reason(refused: ValidationError | ValueError) -> str:
    # Complement raises through Pydantic, a loadout raises a bare ValueError.
    if isinstance(refused, ValidationError):
        return refused.errors()[0]["msg"].removeprefix("Value error, ")
    return str(refused)


class Volley(BaseModel):
    """One unit shooting another, and what the shot has to travel through."""

    model_config = ConfigDict(extra="forbid")

    shooter: Deployment
    target: Deployment
    distance: int = Field(ge=0)
    moved: bool = False
    battle_strength: int | None = Field(default=None, ge=1)


@app.post("/volley", summary="Resolve one volley of shooting, and the panic it causes")
def volley(request: Volley, data: Corpus) -> VolleyReport:
    """Shoot one unit at another and resolve the panic its casualties cause.

    ``distance`` is in inches; ``moved`` says the shooter moved this turn.
    ``battle_strength`` is the target's size at the start of the battle, which
    governs the Fall Back or Flee split; it defaults to the size it is shot at.

    A side the corpus cannot field is refused before any dice are walked: an
    unknown slug is a 404, and a size, option or weapon the datasheet does not
    allow is a 422 naming which side asked for it. The shooter must carry
    something with a missile profile.

    Returns:
        The volley resolved: the scores each roll needs, the wound and casualty
        distributions, what the target's nerve does, and every rule the volley
        holds without applying.
    """
    return VolleyReport.of(*_fired(request, data))


@app.post("/graph/volley", summary="Evaluate the volley program a volley resolves")
def graph_volley(request: Volley, data: Corpus) -> dict[str, object]:
    """Fire the volley ``/volley`` fires, and show the program it ran on.

    Returns:
        The evaluated volley program, in the lane ``/volley`` reports on.
    """
    *_, fired = _fired(request, data)
    return fired.evaluated.lane.to_view()


def _fired(request: Volley, data: TOWRepository) -> tuple[Contingent, Contingent, Fired]:
    game = TOWGame.assemble(data)
    shooter = _deploy(game, data, request.shooter, "shooter", MISSILE)
    if request.moved:
        shooter = shooter.after(Movement.march())
    target = _deploy(game, data, request.target, "target", MELEE)
    fired = game.shooting.volley(
        shooter,
        target,
        distance=request.distance,
        battle_strength=request.battle_strength,
    )
    return shooter, target, fired


@app.get("/weapons", summary="List every weapon entry in the corpus")
def list_weapons(data: Corpus) -> list[WeaponSummary]:
    """List the weapon entries, ordered by slug.

    Returns:
        One summary per weapon.
    """
    return [WeaponSummary.of(weapon) for _, weapon in sorted(data.weapons.items())]


@app.get("/weapons/{slug}", summary="Read one weapon entry")
def read_weapon(slug: str, data: Corpus) -> WeaponDetail:
    """Read a weapon entry in full: its profiles, its rules, its restrictions.

    Returns:
        The entry, each profile's printed rule names carrying what they resolve
        to.

    Raises:
        HTTPException: 404, when no entry carries the slug.
    """
    weapon = data.weapons.get(slug)
    if weapon is None:
        raise HTTPException(status_code=404, detail=f"no weapon {slug!r}")
    return WeaponDetail.of(weapon, data.rules)


@app.get("/armour", summary="List every armour entry in the corpus")
def list_armour(data: Corpus) -> list[Armour]:
    """List the armour entries, ordered by slug.

    An armour entry prints no rules and no long text, so a listing serves each
    one whole rather than projecting a summary that could drift from it.

    Returns:
        Every entry.
    """
    return [armour for _, armour in sorted(data.armoury.items())]


@app.get("/armour/{slug}", summary="Read one armour entry")
def read_armour(slug: str, data: Corpus) -> Armour:
    """Read one armour entry: its armour value, and what it leaves out.

    Returns:
        The entry.

    Raises:
        HTTPException: 404, when no entry carries the slug.
    """
    armour = data.armoury.get(slug)
    if armour is None:
        raise HTTPException(status_code=404, detail=f"no armour {slug!r}")
    return armour


@app.get("/rules", summary="List every rule entry in the corpus")
def list_rules(data: Corpus) -> list[RuleSummary]:
    """List the rule entries, ordered by slug.

    Returns:
        One summary per entry.
    """
    return rule_summaries(data)


@app.get("/coverage", summary="Report what the corpus prints that the engine never reads")
def read_coverage(data: Corpus) -> Coverage:
    """Report every gap between the corpus and the engine, with the ledger's reason for each.

    Returns:
        The gaps, and the ledger entries no gap needs any more.
    """
    return coverage(data)


@app.get("/rules/{slug}", summary="Read one rule entry")
def read_rule(slug: str, data: Corpus) -> Rule:
    """Read a rule entry in full: its text, its effects, and what it leaves out.

    Returns:
        The rule entry.

    Raises:
        HTTPException: 404, when no entry carries the slug. A rule the corpus
            prints without an entry has none to read; ``/coverage``
            names those.
    """
    rule = data.rules.get(slug)
    if rule is None:
        raise HTTPException(status_code=404, detail=f"no rule entry {slug!r}")
    return rule
