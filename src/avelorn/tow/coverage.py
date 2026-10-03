"""What the corpus prints that the engine never reads, checked against the ledger.

A gap is an error unless it is acknowledged. :func:`coverage` scans the corpus
for every :class:`~avelorn.tow.schema.ledger.GapKind` and matches each gap
against ``data/tow/unmodelled.yaml``: a gap with no entry is unacknowledged, an
entry with no gap is stale. The CLI, the API and the gate test all read this
one report.

The scan reads the corpus, not the rule registry, since a rule with no entry is
invisible there. An entry with no effects is not a gap kind: no such entry may
be filed (``test_every_rule_entry_carries_effects``).
"""

from collections import defaultdict
from collections.abc import Iterator
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from avelorn.core.registry import Registry, UnknownNameError
from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.rules import printed_rule, split_parameter
from avelorn.tow.schema.ledger import Acknowledgement, GapKind
from avelorn.tow.schema.rule import GrantEffect, Rule, references_parameter
from avelorn.tow.schema.unit import OptionKind, UnitOption


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


def printed_rules(data: TOWRepository) -> Iterator[tuple[str, Site]]:
    """Every rule reference the corpus prints, with where it is printed.

    A unit's own rules, the rules its options add, a troop type's rules, a
    weapon profile's rules, and the rules another rule grants.

    Yields:
        The rule name as printed, and the entry printing it.
    """
    for slug, unit in sorted(data.units.items()):
        for name in unit.special_rules:
            yield name, Site(entry=Entry.UNIT, id=slug)
        for option in unit.options:
            for name in option.adds_rules:
                yield name, Site(entry=Entry.OPTION, id=f"{slug}/{option.name}")
    for slug, troop_type in sorted(data.troop_types.items()):
        for name in troop_type.special_rules:
            yield name, Site(entry=Entry.TROOP_TYPE, id=slug)
    for slug, weapon in sorted(data.weapons.items()):
        for profile in weapon.profiles:
            for name in profile.special_rules:
                yield name, Site(entry=Entry.WEAPON, id=slug)
    for slug, rule in sorted(data.rules.items()):
        for effect in rule.effects:
            if isinstance(effect, GrantEffect):
                yield effect.grants, Site(entry=Entry.RULE, id=slug)


def rule_gap(name: str, rules: Registry[Rule]) -> GapKind | None:
    """How a printed rule reference fails to reach the maths, if it does.

    Returns:
        The gap kind, or None when the reference resolves with every
        parameter bound.
    """
    rule = printed_rule(name, rules)
    if rule is not None:
        unbound = any(references_parameter(effect) for effect in rule.effects)
        return GapKind.PARAMETER_UNBOUND if unbound else None
    placeholder, _ = split_parameter(name)
    try:
        rules.by_name(placeholder)
    except UnknownNameError:
        return GapKind.RULE_WITHOUT_ENTRY
    return GapKind.PARAMETER_UNBOUND


def _order(kind: GapKind, subject: str) -> tuple[int, str]:
    return list(GapKind).index(kind), subject


def _scan(data: TOWRepository) -> Iterator[tuple[GapKind, str, Site]]:
    """Every gap occurrence in the corpus, one per place it occurs.

    Yields:
        The gap's kind, its ledger subject, and the entry it occurs in.
    """
    for name, site in printed_rules(data):
        if (kind := rule_gap(name, data.rules)) is not None:
            yield kind, name, site
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
    if option.applies_to is not None:
        return True
    return option.points_budget is None and not any(folds)
