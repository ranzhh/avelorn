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

from collections.abc import Callable
from importlib.metadata import version
from typing import Annotated, Literal, NamedTuple

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from avelorn.tow.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.data import TOWRepository, default_repository
from avelorn.tow.game import TOWGame
from avelorn.tow.muster import Complement
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.weapon import Weapon
from avelorn.tow.views import (
    FightReport,
    MusteredUnit,
    RuleSummary,
    UnitDetail,
    UnitSummary,
    UnmodelledRule,
    VolleyReport,
    WeaponDetail,
    WeaponSummary,
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
    """What a caller asks to field: a datasheet, a model count, and options by name."""

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
    a = _deploy(game, data, request.a, "side a")
    b = _deploy(game, data, request.b, "side b")
    if request.charge is not None:
        charged = Charge(request.charge.full_inches, request.charge.arc)
        if request.charge.side == "a":
            a = a.charging(charged)
        else:
            b = b.charging(charged)
    fought = game.combat.fight(a, b)
    scored = game.combat.result(fought)
    return FightReport.of(a, b, fought, scored, game.combat.break_test(scored, a, b))


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
    # How far the shot carries, in inches. Omitted, the long-range modifier
    # cannot be settled either way, so it is left unapplied and said so in
    # not_modelled rather than assumed to be short range.
    distance: int | None = Field(default=None, ge=0)
    # Situational to-hit modifiers the caller knows and the corpus cannot:
    # cover, a large target, a unit that moved.
    hit_modifier: int = 0
    # The target's model count at the start of the battle, which governs the
    # printed Fall Back or Flee split. Defaults to the size it is shot at --
    # a unit that has taken no casualties yet.
    battle_strength: int | None = Field(default=None, ge=1)


@app.post("/volley", summary="Resolve one volley of shooting, and the panic it causes")
def volley(request: Volley, data: Corpus) -> VolleyReport:
    """Shoot one unit at another and resolve the panic its casualties cause.

    One volley: shots are counted, rolled to hit and to wound, saved against,
    and the survivors tally into a casualty distribution the target then tests
    its nerve against. The to-hit target reported is the one the volley used,
    with the range and movement modifiers already folded in.

    A side the corpus cannot field is refused before any dice are walked: an
    unknown slug is a 404, and a size, option or weapon the datasheet does not
    allow is a 422 naming which side asked for it. The shooter must carry
    something with a missile profile.

    Returns:
        The volley resolved: the effective targets, the wound and casualty
        distributions, what the target's nerve does, and every rule the engine
        held without applying.
    """
    game = TOWGame.assemble(data)
    shooter = _deploy(game, data, request.shooter, "shooter", MISSILE)
    target = _deploy(game, data, request.target, "target", MELEE)
    fired = game.shooting.volley(
        shooter, target, distance=request.distance, hit_modifier=request.hit_modifier
    )
    panicked = game.shooting.make_panic_tests(
        fired, target, battle_strength=request.battle_strength
    )
    return VolleyReport.of(shooter, target, fired, panicked)


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
