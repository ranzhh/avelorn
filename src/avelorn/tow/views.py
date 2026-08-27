"""What a caller shows of the corpus: the views both surfaces present.

The command line and the HTTP API are windows on the same data, and it must look
the same through either. How they render differs -- aligned columns against JSON
-- but *what is carried* is declared once, here, so neither can quietly fall
behind the other.

A listing answers "what is in the corpus": :class:`UnitSummary` and
:class:`RuleSummary`, deliberately not the whole entry, since serving every
unit's profiles and options at once makes a listing grow with the corpus rather
than with its length. Reading one entry answers everything else. A rule's view is
the schema type itself (:class:`~avelorn.tow.schema.rule.Rule`) -- nothing to
project, so projecting it would only create something to drift. A datasheet's is
:class:`UnitDetail`, the schema type but for one field: the rule names it prints
arrive resolved, each carrying the entry it addresses. That much has to be
projected, because a printed name does not become a slug by slugifying it --
"Impact Hits (D3)" is filed under ``impact-hits`` -- and a caller left to derive
it would derive it wrong more often than right.

:func:`unmodelled_rules` is the third view and the odd one: not a projection of
an entry but a report over the whole corpus, naming every rule some unit or
weapon prints that never reaches the maths. The engine says as much one action at
a time, in the "special rule not factored" notes; this is the same honesty
totalled up, and it is the reason the report has to scan units and weapons rather
than read the rule registry alone -- a rule with no entry is invisible there.
"""

from collections import defaultdict
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from avelorn.core.distribution import Probability
from avelorn.core.registry import Registry
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.rules import printed_rule
from avelorn.tow.muster import Complement
from avelorn.tow.phases.combat import BreakResult, CombatResult, FightResult, SideBreak
from avelorn.tow.phases.shooting import PanicResult, ShootingResult
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import TroopType, Unit, UnitSize


class UnitSummary(BaseModel):
    """A datasheet as a listing shows it: what it costs, how it is fielded, who fields it.

    ``armies`` is every army filing the datasheet, by slug, which a listing
    groups by. It is plural because a slug may be filed under several -- a
    mount or a beast that more than one army takes -- so a unit belongs to as
    many branches of a browser as field it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    points: int
    unit_size: UnitSize
    troop_type: TroopType
    armies: list[str]

    @classmethod
    def of(cls, unit: Unit, armies: Sequence[str]) -> "UnitSummary":
        """Summarise one datasheet.

        Returns:
            The listing view of ``unit``, told which armies field it.
        """
        return cls(
            id=unit.id,
            name=unit.name,
            points=unit.points,
            unit_size=unit.unit_size,
            troop_type=unit.troop_type,
            armies=list(armies),
        )


class PrintedRule(BaseModel):
    """A rule name as a datasheet prints it, and the entry it resolves to.

    ``slug`` addresses the entry, so a caller can link to it without knowing
    how a printed name finds its file -- an exact match, or the "(X)" template
    a parameterised name comes from ("Impact Hits (D3)" is filed under
    ``impact-hits``). ``None`` says the corpus prints this name and nothing
    models it: the fact :func:`unmodelled_rules` reports over the whole corpus,
    said here on the datasheet that prints it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str | None

    @classmethod
    def of(cls, printed: str, rules: Registry[Rule]) -> "PrintedRule":
        """Resolve one printed name.

        Returns:
            The name, with the slug of the entry it resolves to or ``None``.
        """
        entry = printed_rule(printed, rules)
        return cls(name=printed, slug=None if entry is None else entry.id)


class UnitDetail(Unit):
    """A datasheet as reading one shows it: the entry, its rule names resolved.

    Everything :class:`~avelorn.tow.schema.unit.Unit` prints, except that a
    special rule arrives as a :class:`PrintedRule` rather than a bare string.
    Resolving on the way out is what keeps a caller from re-deriving it: a
    printed name does not become a slug by slugifying it.
    """

    special_rules: list[PrintedRule]

    @classmethod
    def of(cls, unit: Unit, rules: Registry[Rule]) -> "UnitDetail":
        """Resolve a datasheet's printed rule names.

        Returns:
            The detail view of ``unit``.
        """
        return cls.model_validate(
            {
                **unit.model_dump(),
                "special_rules": [PrintedRule.of(name, rules) for name in unit.special_rules],
            }
        )


class Wieldable(BaseModel):
    """A weapon a block carries, and which phases can put it in hand.

    A bow has no Combat profile and a hand weapon no missile one, so a caller
    resolving a melee or a volley must not offer the wrong half. The facts
    belong here rather than in the caller because they are read off the weapon
    entry, and a caller guessing from the name would be guessing.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    fights: bool
    shoots: bool


class Footprint(BaseModel):
    """The rectangle a block occupies once it forms up.

    The formation it takes, and the table space that costs: ``files`` models
    across by ``ranks`` deep, each model on a base of the datasheet's size. A
    rear rank standing short still occupies its whole rank, so the depth is the
    ranks rather than the models.
    """

    model_config = ConfigDict(extra="forbid")

    files: int
    ranks: int
    width_mm: int
    depth_mm: int

    @classmethod
    def of(cls, formed: Contingent) -> "Footprint | None":
        """Measure what a fielded block stands on.

        Returns:
            The rectangle, or None where the datasheet prints no base size.
        """
        base = formed.unit.base_size
        if base is None:
            return None
        formation = formed.formation
        return cls(
            files=formation.files,
            ranks=formation.ranks,
            width_mm=formation.files * base.width_mm,
            depth_mm=formation.ranks * base.depth_mm,
        )


class MusteredUnit(BaseModel):
    """A block of an army list: a datasheet sized and equipped, and what it costs.

    The view over :class:`~avelorn.tow.muster.Complement`. It carries the
    datasheet by slug rather than whole, because a list is read as a list --
    a caller wanting the profiles follows ``unit`` to the datasheet route.
    ``equipment`` and ``special_rules`` are the effective ones, the chosen
    options' adds and removes already folded in, so a block says what the
    models actually carry rather than what the datasheet offered. ``weapons``
    narrows the equipment to the weapons among it, each saying whether it can
    be used in close combat -- what a caller naming a weapon chooses from.
    ``footprint`` is the table space the block takes, at the frontage asked for
    or the datasheet's default, which a caller drawing it needs and cannot
    derive from a slug.
    """

    model_config = ConfigDict(extra="forbid")

    unit: str
    name: str
    size: int
    options: list[str]
    points: int
    equipment: list[str]
    weapons: list[Wieldable]
    special_rules: list[PrintedRule]
    footprint: Footprint | None

    @classmethod
    def of(
        cls, complement: Complement, rules: Registry[Rule], frontage: int | None = None
    ) -> "MusteredUnit":
        """Cost and equip one block, formed up as wide as asked.

        Args:
            complement: The sized and equipped datasheet.
            rules: The registry its printed rule names resolve against.
            frontage: The formation width in files; the troop type's default
                when omitted.

        Returns:
            The block's view, its rule names resolved as a datasheet's are.
        """
        formed = Contingent.field(complement, frontage=frontage)
        return cls(
            unit=complement.unit.id,
            name=complement.unit.name,
            size=complement.size,
            options=list(complement.options),
            points=complement.points,
            equipment=complement.equipment,
            footprint=Footprint.of(formed),
            # What the block could fight with, which is the equipment that
            # resolves to a weapon rather than to armour.
            weapons=[
                Wieldable(
                    name=weapon.name,
                    fights=weapon.combat_profile is not None,
                    shoots=weapon.missile_profile is not None,
                )
                for weapon in formed.loadout.weapons
            ],
            special_rules=[PrintedRule.of(name, rules) for name in complement.special_rules],
        )


class FightSide(BaseModel):
    """One side of a resolved round: what it fielded, what it lost, whether it held.

    ``casualties`` is the marginal distribution of models this side loses in
    the melee -- index ``k`` is the probability it loses exactly ``k`` -- and
    ``expected_casualties`` its mean, which is the number an averaging
    simulator would report and the one the distribution exists to replace.
    The three Break-test figures are conditional on nothing: each is the
    probability of that outcome *over the whole round*, so they sum to this
    side's chance of losing, and a side that mostly wins shows three small
    numbers.
    """

    model_config = ConfigDict(extra="forbid")

    unit: str
    name: str
    size: int
    weapon: str
    initiative: int
    rank_bonus: int
    unit_strength: int
    casualties: list[float]
    expected_casualties: float
    gives_ground: float
    falls_back: float
    breaks: float


class FightReport(BaseModel):
    """One round of close combat, resolved exactly.

    The engine works in rationals; these are floats, because JSON has no
    other number and a caller plotting a distribution wants one. The exact
    values stay reachable from Python.

    ``first_striker`` names the side Initiative put first, or is ``None`` when
    equal Initiative made the blows simultaneous -- a Great Weapon's Strike
    Last is why a higher-Initiative unit can still swing second.
    ``not_modelled`` is every note the round produced, gathered from the
    melee, the scoring and the Break test: what the engine held and did not
    apply, so a figure is never quietly wrong.
    """

    model_config = ConfigDict(extra="forbid")

    a: FightSide
    b: FightSide
    p_a_wins: float
    p_draw: float
    p_b_wins: float
    first_striker: str | None
    margin: dict[int, float]
    not_modelled: list[str]

    @classmethod
    def of(
        cls,
        a: Contingent,
        b: Contingent,
        fought: FightResult,
        scored: CombatResult,
        broke: BreakResult,
    ) -> "FightReport":
        """Gather a resolved round into one answer.

        Returns:
            The report both surfaces show.
        """
        first = None
        if fought.first_striker is a:
            first = "a"
        elif fought.first_striker is b:
            first = "b"
        return cls(
            a=_side(
                a,
                fought.a_casualties,
                fought.a_initiative.value,
                fought.a_rank_bonus,
                fought.a_unit_strength,
                broke.a,
            ),
            b=_side(
                b,
                fought.b_casualties,
                fought.b_initiative.value,
                fought.b_rank_bonus,
                fought.b_unit_strength,
                broke.b,
            ),
            p_a_wins=float(scored.p_a_wins),
            p_draw=float(scored.p_draw),
            p_b_wins=float(scored.p_b_wins),
            first_striker=first,
            margin={lead: float(mass) for lead, mass in sorted(scored.margin.items())},
            not_modelled=sorted({*fought.notes, *scored.notes, *broke.notes}),
        )


def _side(
    side: Contingent,
    casualties: Sequence[Probability],
    initiative: int,
    rank_bonus: int,
    unit_strength: int,
    broke: SideBreak,
) -> FightSide:
    # The weapon is set before a contingent fights, so in_hand() is never None
    # here; a caller that skipped arming it would have failed in the resolver.
    losses = [float(mass) for mass in casualties]
    return FightSide(
        unit=side.unit.id,
        name=side.unit.name,
        size=side.models,
        weapon=side.in_hand().name,
        initiative=initiative,
        rank_bonus=rank_bonus,
        unit_strength=unit_strength,
        casualties=losses,
        expected_casualties=sum(k * mass for k, mass in enumerate(losses)),
        gives_ground=float(broke.p_gives_ground),
        falls_back=float(broke.p_falls_back),
        breaks=float(broke.p_breaks),
    )


class Panic(BaseModel):
    """What a volley's casualties do to the target's nerve.

    ``tests`` is the chance the unit is forced to test at all -- it lost more
    than a quarter of the models it started the phase with, and something is
    left to test. The four outcomes below it are unconditional and exhaust the
    space: a unit that is never forced to test simply ``holds``.
    """

    model_config = ConfigDict(extra="forbid")

    tests: float
    holds: float
    falls_back: float
    flees: float
    destroyed: float
    # The rule that re-rolled a failed test, if the target carries one.
    reroll_from: str | None


class Volleyed(BaseModel):
    """A unit in a volley: the one shooting, or the one shot at."""

    model_config = ConfigDict(extra="forbid")

    unit: str
    name: str
    size: int
    # The weapon loosed, on the shooter; the target is not armed for this.
    weapon: str | None = None


class VolleyReport(BaseModel):
    """One volley of shooting, resolved exactly, and what it did to the target's nerve.

    The targets are the ones the volley actually used, not the ones printed:
    ``hit_target`` already carries the range and movement modifiers, which is
    why the same bow needs a 3+ up close and a 4+ beyond half range. A target
    is ``None`` where the stage does not apply -- no armour save to take, no
    ward to attempt.

    ``wounds`` is the distribution of unsaved wounds and ``casualties`` the
    models removed; they differ only when the volley would overkill the unit
    or its models have more than one Wound.
    """

    model_config = ConfigDict(extra="forbid")

    shooter: Volleyed
    target: Volleyed
    shots: int
    hit_target: int
    wound_target: int | None
    save_target: int | None
    ward_target: int | None
    p_hit: float
    p_wound: float
    p_unsaved: float
    wounds: list[float]
    casualties: list[float]
    expected_wounds: float
    expected_casualties: float
    panic: Panic
    not_modelled: list[str]

    @classmethod
    def of(
        cls,
        shooter: Contingent,
        target: Contingent,
        volley: ShootingResult,
        panicked: PanicResult,
    ) -> "VolleyReport":
        """Gather a resolved volley and its panic step into one answer.

        Returns:
            The report both surfaces show.
        """
        return cls(
            shooter=Volleyed(
                unit=shooter.unit.id,
                name=shooter.unit.name,
                size=shooter.models,
                weapon=shooter.in_hand().name,
            ),
            target=Volleyed(unit=target.unit.id, name=target.unit.name, size=target.models),
            shots=volley.shots,
            hit_target=volley.hit_target,
            wound_target=volley.wound_target,
            save_target=volley.save_target,
            ward_target=volley.ward_target,
            p_hit=float(volley.p_hit),
            p_wound=float(volley.p_wound),
            p_unsaved=float(volley.p_unsaved),
            wounds=[float(mass) for mass in volley.distribution],
            casualties=[float(mass) for mass in volley.casualties],
            expected_wounds=float(volley.expected_wounds),
            expected_casualties=float(volley.expected_casualties),
            panic=Panic(
                tests=float(panicked.p_test),
                holds=float(panicked.p_holds),
                falls_back=float(panicked.p_falls_back),
                flees=float(panicked.p_flees),
                destroyed=float(panicked.p_destroyed),
                reroll_from=panicked.reroll_from,
            ),
            not_modelled=sorted(set(volley.notes)),
        )


class RuleSummary(BaseModel):
    """A rule entry as a listing shows it: what it is, and whether it reaches the maths.

    ``factors`` is the honest bit. An entry carries effects or it does not, and
    one that does not is text the engine holds and never applies -- Killing Blow
    is the standing example, its "no armour save allowed" having no word in the
    effect vocabulary. ``references`` counts the units and weapons printing it,
    so a listing sorts by what would matter most to model next.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    category: str | None
    factors: bool
    references: int

    @classmethod
    def of(cls, rule: Rule, references: int) -> "RuleSummary":
        """Summarise one rule entry.

        Returns:
            The listing view of ``rule``.
        """
        return cls(
            id=rule.id,
            name=rule.name,
            category=rule.category,
            factors=bool(rule.effects),
            references=references,
        )


class UnmodelledRule(BaseModel):
    """A rule the corpus prints that has no entry, so the engine cannot apply it.

    Keyed by printed ``name``: that is how a datasheet references a rule, and
    with no entry it is the only handle the rule has. ``units`` and ``weapons``
    name who prints it, which is what makes the report actionable -- a rule
    nothing carries is not worth modelling yet.

    An entry that carried no effects would be unapplied too, but no such entry
    is allowed in ``data/`` (``test_every_rule_entry_carries_effects``): a rule
    that cannot fold is filed by not filing it. So a missing entry is the only
    way a printed rule goes unmodelled, and this needs no reason field.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    units: tuple[str, ...]
    weapons: tuple[str, ...]


def rule_summaries(data: TOWRepository) -> list[RuleSummary]:
    """Every rule entry in the corpus, ordered by slug.

    Returns:
        One summary per entry.
    """
    units, weapons = _references(data)
    return [
        RuleSummary.of(rule, len(units[rule.name]) + len(weapons[rule.name]))
        for _, rule in sorted(data.rules.items())
    ]


def unmodelled_rules(data: TOWRepository) -> list[UnmodelledRule]:
    """Every rule the corpus prints that never reaches the maths.

    Found by scanning what units and weapons print, not by reading the rule
    registry: a rule with no file is nowhere in the registry, which is the whole
    point of the report.

    Returns:
        The report, ordered by how many entries print each rule, then by name.
    """
    units, weapons = _references(data)
    report = []
    for name in set(units) | set(weapons):
        # Resolved the way fielding resolves it, so a printed parameter finds
        # the entry filed under "(X)": Armour Bane (1) is modelled, and reporting
        # it as missing because no file carries that exact name would be a lie.
        if printed_rule(name, data.rules) is not None:
            continue
        report.append(
            UnmodelledRule(
                name=name,
                units=tuple(sorted(units[name])),
                weapons=tuple(sorted(weapons[name])),
            )
        )
    report.sort(key=lambda r: (-len(r.units) - len(r.weapons), r.name))
    return report


def _references(data: TOWRepository) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Which units and weapons print each rule name.

    A unit prints its own special rules and those its troop type confers, since
    both reach the body that fights. A weapon prints the rules on each of its
    profiles.

    Returns:
        Rule name to unit slugs, and rule name to weapon slugs.
    """
    units: dict[str, set[str]] = defaultdict(set)
    weapons: dict[str, set[str]] = defaultdict(set)
    for slug, unit in data.units.items():
        conferred = (
            () if unit.troop_type_profile is None else unit.troop_type_profile.special_rules
        )
        for name in (*unit.special_rules, *conferred):
            units[name].add(slug)
    for slug, weapon in data.weapons.items():
        for profile in weapon.profiles:
            for name in profile.special_rules:
                weapons[name].add(slug)
    return units, weapons
