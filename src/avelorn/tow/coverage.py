"""What the corpus prints that the engine never reads, checked against the ledger.

A gap is an error unless it is acknowledged. :func:`coverage` scans the corpus
for every :class:`~avelorn.tow.schema.ledger.GapKind` and matches each gap
against ``data/tow/unmodelled.yaml``: a gap with no entry is unacknowledged, an
entry with no gap is stale. The CLI, the API and the gate test all read this
one report.

The scan reads the corpus, not the rule registry, since a rule nothing
references is no gap.
"""

from collections import defaultdict
from collections.abc import Iterator
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.effect import Effect
from avelorn.tow.schema.ledger import Acknowledgement, GapKind
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import GrantEffect, Rule
from avelorn.tow.schema.step import Step, StepSequence
from avelorn.tow.schema.unit import OptionKind, UnitOption
from avelorn.tow.steps import STEPS


class Entry(StrEnum):
    """The kind of corpus entry a gap occurs in."""

    UNIT = "unit"
    TROOP_TYPE = "troop-type"
    WEAPON = "weapon"
    ARMOUR = "armour"
    OPTION = "option"
    RULE = "rule"


class Site(BaseModel):
    """Where a gap occurs: an entry, by slug (``<unit>/<option>`` for an option)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entry: Entry
    id: str


class Gap(BaseModel):
    """One gap, where it occurs, and the ledger's reason for it if acknowledged.

    ``reason`` is None for an unacknowledged gap, which is what fails the gate.
    """

    model_config = ConfigDict(extra="forbid")

    kind: GapKind
    subject: str
    sites: tuple[Site, ...]
    reason: str | None
    issue: int | None


class Coverage(BaseModel):
    """The gaps found, ordered by kind then subject, and the ledger entries nothing needs."""

    model_config = ConfigDict(extra="forbid")

    gaps: list[Gap]
    stale: list[Acknowledgement]

    @property
    def acknowledged(self) -> bool:
        """Whether the ledger matches the corpus: every gap acknowledged, no entry stale."""
        return not self.stale and all(gap.reason is not None for gap in self.gaps)


# The engine reads no command model, so each kind is one gap across every datasheet.
_COMMAND = {OptionKind.CHAMPION, OptionKind.STANDARD_BEARER, OptionKind.MUSICIAN}


def coverage(data: TOWRepository) -> Coverage:
    """Scan the corpus for gaps and match them against the ledger.

    Returns:
        Every gap with its acknowledgement, and every stale ledger entry.
    """
    found: dict[tuple[GapKind, str], set[Site]] = defaultdict(set)
    for kind, subject, site in _scan(data):
        found[kind, subject].add(site)
    ledger = {(entry.kind, entry.subject): entry for entry in data.ledger.root}
    gaps = []
    for (kind, subject), sites in sorted(found.items(), key=lambda item: _order(*item[0])):
        entry = ledger.get((kind, subject))
        gaps.append(
            Gap(
                kind=kind,
                subject=subject,
                sites=tuple(sorted(sites, key=lambda site: (site.entry, site.id))),
                reason=None if entry is None else entry.reason,
                issue=None if entry is None else entry.issue,
            )
        )
    stale = [entry for key, entry in ledger.items() if key not in found]
    return Coverage(gaps=gaps, stale=sorted(stale, key=lambda e: _order(e.kind, e.subject)))


def rule_references(data: TOWRepository) -> Iterator[tuple[RuleRef, Site]]:
    """Every rule reference the corpus prints, with where it is printed.

    A unit's own rules, the rules its options add, a troop type's rules, a
    weapon profile's rules, and the rules another rule grants.

    Yields:
        The reference, and the entry printing it.
    """
    for slug, unit in sorted(data.units.items()):
        for reference in unit.special_rules:
            yield reference, Site(entry=Entry.UNIT, id=slug)
        for option in unit.options:
            for reference in option.adds_rules:
                yield reference, Site(entry=Entry.OPTION, id=f"{slug}/{option.name}")
    for slug, troop_type in sorted(data.troop_types.items()):
        for reference in troop_type.special_rules:
            yield reference, Site(entry=Entry.TROOP_TYPE, id=slug)
    for slug, weapon in sorted(data.weapons.items()):
        for profile in weapon.profiles:
            for reference in profile.special_rules:
                yield reference, Site(entry=Entry.WEAPON, id=slug)
    for slug, rule in sorted(data.rules.items()):
        site = Site(entry=Entry.RULE, id=slug)
        for effect in rule.effects:
            if isinstance(effect, GrantEffect):
                yield effect.grants, site
        for addressed in () if rule.graph is None else rule.graph.effects:
            if addressed.grants is not None:
                yield addressed.grants, site


def rule_gap(rule: Rule) -> GapKind | None:
    """How a referenced rule fails to reach the maths, if it does.

    A reference that names no rule or does not bind its X fails the load, so
    what is left is a rule the engine holds as text only.

    Returns:
        The gap kind, or None when the rule carries effects.
    """
    return None if rule.effects else GapKind.RULE_WITHOUT_EFFECTS


def unattached(effect: Effect) -> Iterator[tuple[StepSequence, Step]]:
    """Every printed step the effect needs where no program registers it.

    The landing is needed in each sequence it can land in. A trigger, the
    block it is narrowed to, or a step read as a fact is needed in at least
    one sequence that prints it.

    Yields:
        The sequence and the step.
    """
    if effect.at is not None:
        for sequence in effect.at.sequences:
            if (sequence, effect.at.step) not in STEPS:
                yield sequence, effect.at.step
    for step in sorted(_read_steps(effect)):
        if not any((sequence, step) in STEPS for sequence in step.sequences):
            yield from ((sequence, step) for sequence in step.sequences)


def _read_steps(effect: Effect) -> set[Step]:
    named = {Step(fact) for fact in effect.facts if fact in Step}
    if effect.when is not None and effect.when.step is not None:
        named.add(effect.when.step)
    if effect.at is not None and isinstance(effect.at.in_, Step):
        named.add(effect.at.in_)
    return named


def _graph_gaps(slug: str, rule: Rule) -> Iterator[tuple[GapKind, str, Site]]:
    """The gaps in a rule as the graph reads it.

    Yields:
        Each gap's kind, its ledger subject, and the rule as its site.
    """
    if rule.graph is None:
        return
    site = Site(entry=Entry.RULE, id=slug)
    for effect in rule.graph.effects:
        for sequence, step in unattached(effect):
            yield GapKind.UNATTACHED_EFFECT, f"{slug}/{sequence}/{step}", site
    for mechanic in rule.graph.needs:
        yield GapKind.MISSING_MECHANIC, mechanic, site


def _order(kind: GapKind, subject: str) -> tuple[int, str]:
    return list(GapKind).index(kind), subject


def _scan(data: TOWRepository) -> Iterator[tuple[GapKind, str, Site]]:
    """Every gap occurrence in the corpus, one per place it occurs.

    Yields:
        The gap's kind, its ledger subject, and the entry it occurs in.
    """
    referenced = set()
    for reference, site in rule_references(data):
        referenced.add(reference.rule)
        if (kind := rule_gap(data.rules[reference.rule])) is not None:
            yield kind, reference.rule, site
    for slug in sorted(referenced):
        yield from _graph_gaps(slug, data.rules[slug])
    for slug, unit in sorted(data.units.items()):
        for row in unit.unread_rows:
            yield GapKind.PROFILE_ROW_UNREAD, f"{slug}/{row.name}", Site(entry=Entry.UNIT, id=slug)
        for option in unit.options:
            subject = f"{slug}/{option.name}"
            bought = Site(entry=Entry.OPTION, id=subject)
            if option.kind in _COMMAND:
                yield GapKind.INERT_OPTION, option.kind.value, bought
            elif _inert(option):
                yield GapKind.INERT_OPTION, subject, bought
    for slug, weapon in sorted(data.weapons.items()):
        if weapon.notes is not None:
            yield GapKind.PRINTED_NOTES, slug, Site(entry=Entry.WEAPON, id=slug)
    for slug, armour in sorted(data.armoury.items()):
        if armour.notes is not None:
            yield GapKind.PRINTED_NOTES, slug, Site(entry=Entry.ARMOUR, id=slug)


def _inert(option: UnitOption) -> bool:
    """Whether buying the option changes nothing the engine reads but its cost.

    An option for one named model never reaches the engine: the muster
    refuses it (#120). A points budget buys magic items, unmodelled (#31) and
    left out here.

    Returns:
        True for an option that is no budget and folds no rule or equipment
        into the whole unit.
    """
    folds = (
        option.adds_rules,
        option.removes_rules,
        option.adds_equipment,
        option.removes_equipment,
    )
    if option.points_budget is not None:
        return False
    return option.applies_to is not None or not any(folds)
