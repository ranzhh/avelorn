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
:class:`UnitDetail`, the schema type but for its references: its equipment and its
rule references arrive resolved, each carrying the name it prints and the entry
it addresses. A rule's name is the rule's own, X substituted -- ``{rule:
impact-hits, X: D3}`` prints "Impact Hits (D3)" -- so a caller never renders it.

What the corpus prints and the engine never reads is not a view of one entry
but a report over all of them: :mod:`avelorn.tow.coverage`.
"""

from collections import defaultdict
from collections.abc import Sequence
from enum import StrEnum
from fractions import Fraction

from pydantic import BaseModel, ConfigDict

from avelorn.core.distribution import Distribution, Probability
from avelorn.core.registry import Registry
from avelorn.tow.contingent import Contingent
from avelorn.tow.coverage import Site, rule_references
from avelorn.tow.data import TOWRepository
from avelorn.tow.muster import Complement
from avelorn.tow.phases.combat import BreakResult, CombatResult, FightResult, SideBreak
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import TroopType, Unit, UnitOption, UnitSize
from avelorn.tow.schema.weapon import Weapon, WeaponProfile, WeaponType
from avelorn.tow.steps import Retreat
from avelorn.tow.volley import Volley


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


class Kind(StrEnum):
    """What a printed name turns out to name.

    A caller following a reference needs the route as well as the slug, and the
    two cannot be inferred from the name: "Daith's Reaper" is filed both as a
    weapon and as the rule that weapon carries.
    """

    RULE = "rule"
    WEAPON = "weapon"
    ARMOUR = "armour"


class Reference(BaseModel):
    """A name as an entry prints it, and the entry it resolves to.

    ``slug`` addresses the entry and ``kind`` says which registry holds it, so a
    caller can follow the name without knowing how one finds its file. A rule's
    name is the rule's display name with the reference's X substituted.

    Both are ``None`` together only for equipment the corpus prints with no
    entry behind it; a rule reference always binds, or the corpus fails to load.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: Kind | None
    slug: str | None

    @classmethod
    def rule(cls, reference: RuleRef, rules: Registry[Rule]) -> "Reference":
        """Resolve one rule reference for presentation.

        Returns:
            The name it prints, carrying the entry it addresses.
        """
        name = rules[reference.rule].display(reference.x)
        return cls(name=name, kind=Kind.RULE, slug=reference.rule)

    @classmethod
    def equipment(
        cls, printed: str, weapons: Registry[Weapon], armoury: Registry[Armour]
    ) -> "Reference":
        """Resolve one printed equipment name against both registries it may sit in.

        A datasheet prints its weapons and its armour in one list, so which of
        the two a name addresses is the server's to say. Weapons are tried
        first; no name is filed as both.

        Returns:
            The name, carrying the entry it addresses or nothing.
        """
        for kind, registry in ((Kind.WEAPON, weapons), (Kind.ARMOUR, armoury)):
            found, _ = registry.resolve([printed])
            if found:
                return cls(name=printed, kind=kind, slug=found[0].id)
        return cls(name=printed, kind=None, slug=None)


class OptionDetail(UnitOption):
    """One option, the rules it adds and removes resolved."""

    adds_rules: list[Reference]
    removes_rules: list[Reference]


class UnitDetail(Unit):
    """A datasheet as reading one shows it: the entry, every printed name resolved.

    Everything :class:`~avelorn.tow.schema.unit.Unit` prints, except that its
    equipment, its special rules and its options' rules arrive as
    :class:`Reference`. Resolving on the way out is what keeps a caller from
    re-deriving it: a printed name does not become a slug by slugifying it, nor
    a reference a name by reading it.
    """

    equipment: list[Reference]
    special_rules: list[Reference]
    options: list[OptionDetail]

    @classmethod
    def of(cls, unit: Unit, data: TOWRepository) -> "UnitDetail":
        """Resolve a datasheet's printed names against the registries holding them.

        Returns:
            The detail view of ``unit``.
        """
        return cls.model_validate(
            {
                **unit.model_dump(),
                "equipment": [
                    Reference.equipment(name, data.weapons, data.armoury)
                    for name in unit.equipment
                ],
                "special_rules": [Reference.rule(ref, data.rules) for ref in unit.special_rules],
                "options": [
                    {
                        **option.model_dump(),
                        "adds_rules": [
                            Reference.rule(ref, data.rules) for ref in option.adds_rules
                        ],
                        "removes_rules": [
                            Reference.rule(ref, data.rules) for ref in option.removes_rules
                        ],
                    }
                    for option in unit.options
                ],
            }
        )


class ProfileDetail(WeaponProfile):
    """One weapon profile, its rule references resolved."""

    special_rules: list[Reference]


class WeaponDetail(Weapon):
    """A weapon entry as reading one shows it, its rule names resolved per profile.

    Per profile rather than pooled, because a weapon with two of them need not
    print the same rules on both -- a Brace of Drakefire Pistols carries Quick
    Shot when fired and Extra Attacks in close combat.
    """

    profiles: list[ProfileDetail]

    @classmethod
    def of(cls, weapon: Weapon, rules: Registry[Rule]) -> "WeaponDetail":
        """Resolve a weapon's rule references, profile by profile.

        Returns:
            The detail view of ``weapon``.
        """
        printed = weapon.model_dump(by_alias=True)
        for profile, resolved in zip(printed["profiles"], weapon.profiles, strict=True):
            profile["special_rules"] = [
                Reference.rule(ref, rules).model_dump() for ref in resolved.special_rules
            ]
        return cls.model_validate(printed)


class WeaponSummary(BaseModel):
    """A weapon as a listing shows it: what it is, and which phase can use it.

    ``fights`` and ``shoots`` are read off the profiles, because a caller
    choosing a weapon for a melee or a volley must not be offered the wrong
    half, and guessing from the name would be guessing.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    weapon_type: WeaponType | None
    fights: bool
    shoots: bool

    @classmethod
    def of(cls, weapon: Weapon) -> "WeaponSummary":
        """Summarise one weapon entry.

        Returns:
            The listing view of ``weapon``.
        """
        return cls(
            id=weapon.id,
            name=weapon.name,
            weapon_type=weapon.weapon_type,
            fights=weapon.combat_profile is not None,
            shoots=weapon.missile_profile is not None,
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
    # The weapon entry this names. A loadout resolves at the muster boundary or
    # refuses, so a carried weapon always has one.
    slug: str
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
    special_rules: list[Reference]
    footprint: Footprint | None

    @classmethod
    def of(
        cls, complement: Complement, rules: Registry[Rule], frontage: int | None = None
    ) -> "MusteredUnit":
        """Cost and equip one block, formed up as wide as asked.

        Args:
            complement: The sized and equipped datasheet.
            rules: The registry its rule references resolve against.
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
                    slug=weapon.id,
                    fights=weapon.combat_profile is not None,
                    shoots=weapon.missile_profile is not None,
                )
                for weapon in formed.loadout.weapons
            ],
            special_rules=[Reference.rule(ref, rules) for ref in complement.special_rules],
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

    Each score is the one the rank and file's roll needed in the volley, with
    every rule in force folded in; scores that differ between attacks are joined
    with "or", and "-" is a roll not made. ``wounds`` is the distribution of
    unsaved wounds and ``casualties`` the models removed; they differ only when
    the volley would overkill the unit or its models have more than one Wound.
    """

    model_config = ConfigDict(extra="forbid")

    shooter: Volleyed
    target: Volleyed
    shots: int
    to_hit: str
    to_wound: str
    armour_save: str
    ward_save: str
    p_unsaved: float
    wounds: list[float]
    casualties: list[float]
    expected_wounds: float
    expected_casualties: float
    panic: Panic
    not_modelled: list[str]

    @classmethod
    def of(cls, shooter: Contingent, target: Contingent, volley: Volley) -> "VolleyReport":
        """Gather a resolved volley into one answer.

        Returns:
            The report both surfaces show.
        """
        retreat = volley.retreat.mass
        return cls(
            shooter=Volleyed(
                unit=shooter.unit.id,
                name=shooter.unit.name,
                size=shooter.models,
                weapon=shooter.in_hand().name,
            ),
            target=Volleyed(unit=target.unit.id, name=target.unit.name, size=target.models),
            shots=volley.shots,
            to_hit=volley.needed("roll-to-hit"),
            to_wound=volley.needed("roll-to-wound"),
            armour_save=volley.needed("make-armour-saves"),
            ward_save=volley.needed("ward-saves"),
            p_unsaved=float(volley.p_unsaved),
            wounds=_listed(volley.unsaved),
            casualties=_listed(volley.casualties),
            expected_wounds=float(volley.unsaved.expect(Fraction)),
            expected_casualties=float(volley.casualties.expect(Fraction)),
            panic=Panic(
                tests=float(volley.tested),
                holds=float(retreat.get(Retreat.HOLDS, 0)),
                falls_back=float(retreat.get(Retreat.FALLS_BACK_IN_GOOD_ORDER, 0)),
                flees=float(retreat.get(Retreat.FLEES, 0)),
                destroyed=float(retreat.get(Retreat.DESTROYED, 0)),
                reroll_from=next(iter(volley.applied("volley/make-panic-tests")), None),
            ),
            not_modelled=list(volley.held),
        )


def _listed(distribution: Distribution[int]) -> list[float]:
    top = max(distribution.mass, default=0)
    return [float(distribution.mass.get(count, 0)) for count in range(top + 1)]


class RuleSummary(BaseModel):
    """A rule entry as a listing shows it: what it is, and whether it reaches the maths.

    ``factors`` says whether the entry carries effects; a text-only entry does
    not. ``references`` counts the places referencing it -- units, options, troop
    types, weapons, and other rules' grants, whatever their X -- so a listing
    sorts by what would matter most to model next.
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


def rule_summaries(data: TOWRepository) -> list[RuleSummary]:
    """Every rule entry in the corpus, ordered by slug.

    Returns:
        One summary per entry.
    """
    printed_by: dict[str, set[Site]] = defaultdict(set)
    for reference, site in rule_references(data):
        printed_by[reference.rule].add(site)
    return [
        RuleSummary.of(rule, len(printed_by[slug])) for slug, rule in sorted(data.rules.items())
    ]
