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

from avelorn.core.registry import Registry
from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.rules import printed_rule
from avelorn.tow.schema.ledger import Acknowledgement, GapKind
from avelorn.tow.schema.rule import PARAMETER_SUFFIX, GrantEffect, Rule, references_parameter
from avelorn.tow.schema.unit import OptionKind, UnitOption


class Entry(StrEnum):
    """The kind of corpus entry a gap occurs in."""

    UNIT = "unit"
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


# Command models and magic-item budgets say what they are by kind or budget, and
# what the engine leaves out of them is general (champions #46, standards #28,
# musicians, magic items #31), not news about one datasheet.
_TYPED = {OptionKind.CHAMPION, OptionKind.STANDARD_BEARER, OptionKind.MUSICIAN}


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


def _order(kind: GapKind, subject: str) -> tuple[int, str]:
    return list(GapKind).index(kind), subject


def _scan(data: TOWRepository) -> Iterator[tuple[GapKind, str, Site]]:
    """Every gap occurrence in the corpus, one per place it occurs.

    Yields:
        The gap's kind, its ledger subject, and the entry it occurs in.
    """
    for slug, unit in sorted(data.units.items()):
        here = Site(entry=Entry.UNIT, id=slug)
        conferred = (
            () if unit.troop_type_profile is None else unit.troop_type_profile.special_rules
        )
        for name in (*unit.special_rules, *conferred):
            if (kind := _rule_gap(name, data.rules)) is not None:
                yield kind, name, here
        for profile in unit.profiles:
            # Characteristic tests read every row's Leadership (Unit.highest);
            # everything else reads only the rank and file and the mount.
            if profile is not unit.main and profile is not unit.mount:
                yield GapKind.PROFILE_ROW_UNREAD, f"{slug}/{profile.name}", here
        for option in unit.options:
            subject = f"{slug}/{option.name}"
            bought = Site(entry=Entry.OPTION, id=subject)
            for name in option.adds_rules:
                if (kind := _rule_gap(name, data.rules)) is not None:
                    yield kind, name, bought
            if _inert(option):
                yield GapKind.INERT_OPTION, subject, bought
    for slug, weapon in sorted(data.weapons.items()):
        here = Site(entry=Entry.WEAPON, id=slug)
        for profile in weapon.profiles:
            for name in profile.special_rules:
                if (kind := _rule_gap(name, data.rules)) is not None:
                    yield kind, name, here
        if weapon.notes is not None:
            yield GapKind.PRINTED_NOTES, slug, here
    for slug, armour in sorted(data.armoury.items()):
        if armour.notes is not None:
            yield GapKind.PRINTED_NOTES, slug, Site(entry=Entry.ARMOUR, id=slug)
    for slug, rule in sorted(data.rules.items()):
        for effect in rule.effects:
            if not isinstance(effect, GrantEffect):
                continue
            if (kind := _rule_gap(effect.grants, data.rules)) is not None:
                yield kind, effect.grants, Site(entry=Entry.RULE, id=slug)


def _rule_gap(name: str, rules: Registry[Rule]) -> GapKind | None:
    """How a printed rule reference fails to reach the maths, if it does.

    Returns:
        The gap kind, or None when the reference resolves with every
        parameter bound.
    """
    rule = printed_rule(name, rules)
    if rule is not None:
        # A dice parameter binds into bare fields only, so a mapping's "X" can survive.
        unbound = any(references_parameter(effect) for effect in rule.effects)
        return GapKind.PARAMETER_UNBOUND if unbound else None
    base, bracket, _ = name.rpartition(" (")
    if bracket and name.endswith(")") and rules.resolve([base + PARAMETER_SUFFIX])[0]:
        return GapKind.PARAMETER_UNBOUND
    return GapKind.RULE_WITHOUT_ENTRY


def _inert(option: UnitOption) -> bool:
    """Whether buying the option changes nothing the engine reads but its cost.

    Returns:
        True for an option that is no command model or budget and folds no
        rule or equipment.
    """
    folds = (
        option.adds_rules,
        option.removes_rules,
        option.adds_equipment,
        option.removes_equipment,
    )
    return option.kind not in _TYPED and option.points_budget is None and not any(folds)
