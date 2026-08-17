"""What a caller shows of the corpus: the views both surfaces present.

The command line and the HTTP API are windows on the same data, and it must look
the same through either. How they render differs -- aligned columns against JSON
-- but *what is carried* is declared once, here, so neither can quietly fall
behind the other.

A listing answers "what is in the corpus": :class:`UnitSummary` and
:class:`RuleSummary`, deliberately not the whole entry, since serving every
unit's profiles and options at once makes a listing grow with the corpus rather
than with its length. Reading one entry answers everything else, and its view is
the schema type itself (:class:`~avelorn.tow.schema.unit.Unit`,
:class:`~avelorn.tow.schema.rule.Rule`) -- there is nothing to project, so
projecting it would only create something to drift.

:func:`unmodelled_rules` is the third view and the odd one: not a projection of
an entry but a report over the whole corpus, naming every rule some unit or
weapon prints that never reaches the maths. The engine says as much one action at
a time, in the "special rule not factored" notes; this is the same honesty
totalled up, and it is the reason the report has to scan units and weapons rather
than read the rule registry alone -- a rule with no entry is invisible there.
"""

from collections import defaultdict
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.rules import printed_rule
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


class Unmodelled(StrEnum):
    """Why a printed rule does not reach the maths."""

    NO_ENTRY = "no entry"
    NO_EFFECTS = "entry carries no effects"


class UnmodelledRule(BaseModel):
    """A rule the corpus prints and the engine does not apply.

    Keyed by printed ``name``, because that is how a datasheet references a rule
    and the only handle a rule with no entry has at all -- ``id`` is None for
    those. ``units`` and ``weapons`` name who prints it, which is what makes the
    report actionable: a rule nothing carries is not worth modelling yet.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    id: str | None
    why: Unmodelled
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

    Two ways that happens: the rule has no entry at all, so it rides along as a
    printed name; or it has an entry that carries no effects. The first is only
    visible by scanning what units and weapons print, since a rule with no file
    is nowhere in the registry. The second is visible in the registry whether
    anything prints it or not, and is listed either way -- Killing Blow is a rule
    the engine does not apply, and its being unused today does not make it
    modelled.

    Returns:
        The report, ordered by how many entries print each rule, then by name.
    """
    units, weapons = _references(data)
    idle = {rule.name for rule in data.rules.values() if not rule.effects}
    report = []
    for name in set(units) | set(weapons) | idle:
        # Resolved the way fielding resolves it, so a printed parameter finds
        # the entry filed under "(X)": Armour Bane (1) is modelled, and reporting
        # it as missing because no file carries that exact name would be a lie.
        entry = printed_rule(name, data.rules)
        if entry is not None and entry.effects:
            continue
        report.append(
            UnmodelledRule(
                name=name,
                id=None if entry is None else entry.id,
                why=Unmodelled.NO_ENTRY if entry is None else Unmodelled.NO_EFFECTS,
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
