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

from pydantic import BaseModel, ConfigDict

from avelorn.core.registry import Registry
from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.rules import printed_rule
from avelorn.tow.muster import Complement
from avelorn.tow.schema.rule import Rule
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


class MusteredUnit(BaseModel):
    """A block of an army list: a datasheet sized and equipped, and what it costs.

    The view over :class:`~avelorn.tow.muster.Complement`. It carries the
    datasheet by slug rather than whole, because a list is read as a list --
    a caller wanting the profiles follows ``unit`` to the datasheet route.
    ``equipment`` and ``special_rules`` are the effective ones, the chosen
    options' adds and removes already folded in, so a block says what the
    models actually carry rather than what the datasheet offered.
    """

    model_config = ConfigDict(extra="forbid")

    unit: str
    name: str
    size: int
    options: list[str]
    points: int
    equipment: list[str]
    special_rules: list[PrintedRule]

    @classmethod
    def of(cls, complement: Complement, rules: Registry[Rule]) -> "MusteredUnit":
        """Cost and equip one block.

        Returns:
            The block's view, its rule names resolved as a datasheet's are.
        """
        return cls(
            unit=complement.unit.id,
            name=complement.unit.name,
            size=complement.size,
            options=list(complement.options),
            points=complement.points,
            equipment=complement.equipment,
            special_rules=[PrintedRule.of(name, rules) for name in complement.special_rules],
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
