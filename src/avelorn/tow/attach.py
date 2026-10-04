"""Attaching the rules of both fielded sides to a program's steps.

No operation is attached yet: a landing names its step and the steps that trigger it.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from avelorn.core.errors import AvelornError
from avelorn.core.graph import Carrier, Holder, Landing, Program, RuleNode, Source, Step
from avelorn.tow.schema.effect import Address, Effect, Role, WeaponMatch
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.step import Step as Printed
from avelorn.tow.schema.step import StepSequence
from avelorn.tow.schema.weapon import Weapon
from avelorn.tow.steps import Fielded, Spec

type Carried = tuple[tuple[RuleRef, Source], ...]

_PHASES = frozenset(Phase)


class AttachError(AvelornError):
    """A rule that cannot be attached at its holder."""


@dataclass(frozen=True)
class Reach:
    """An effect of a rule reaching a step instance for a holder."""

    rule: str
    effect: int
    holder: Holder
    at: Step[Any]


@dataclass(frozen=True)
class Attachment:
    """The rule nodes of one fielding, with every reach behind their landings."""

    nodes: tuple[RuleNode, ...]
    reaches: tuple[Reach, ...]


def rules_in_scope(
    holder: Holder, fielded: Mapping[Side, Fielded], rules: Mapping[str, Rule]
) -> Mapping[str, Carried]:
    """Every rule a holder has, with each source that gives it.

    A side carries its own sources. Each side has the core rules of the phases
    that carry graph effects. Each grant of a rule in scope is read once per
    holder, and gives a source whose ``via`` names the granting node.

    Returns:
        The sources of each rule, by slug.
    """
    holders = _holders(fielded)
    scopes: dict[Side, dict[str, list[tuple[RuleRef, Source]]]] = {
        side: defaultdict(list) for side in fielded
    }
    for side, each in fielded.items():
        for reference, source in each.sources():
            scopes[side][reference.rule].append((reference, source))
        for slug in _core(rules):
            scopes[side][slug].append((RuleRef(rule=slug), Source(Carrier.CORE)))
    read: set[tuple[Side, str]] = set()
    while unread := [
        (side, slug) for side in scopes for slug in scopes[side] if (side, slug) not in read
    ]:
        for side, slug in unread:
            read.add((side, slug))
            via = f"{holders[side]}/{slug}"
            for effect in _effects(rules[slug]):
                if effect.grants is not None:
                    _grant(effect.grants, effect.to, via, side, fielded, scopes)
    return {slug: tuple(sources) for slug, sources in scopes[Side(holder.side)].items()}


def attach_rules(
    program: Program,
    specs: Mapping[Step[Any], Spec],
    fielded: Mapping[Side, Fielded],
    rules: Mapping[str, Rule],
) -> Attachment:
    """The rule nodes both fielded sides give a program, built and not yet attached.

    A rule whose sources at one holder give X values that do not combine fails
    with an :class:`AttachError`.

    Returns:
        The nodes, ordered by side then slug, and every effect that reached a step.
    """
    holders = _holders(fielded)
    scopes = {side: rules_in_scope(holder, fielded, rules) for side, holder in holders.items()}
    run = {spec.sequence for spec in specs.values()}
    printed = {spec.key for spec in specs.values()}
    landed: dict[tuple[Side, str], dict[Step[Any], list[Step[Any]]]] = defaultdict(dict)
    kept: set[tuple[Side, str]] = set()
    reaches: list[Reach] = []
    for side, scope in scopes.items():
        for slug in scope:
            effects = _effects(rules[slug])
            if not effects:
                kept.add((side, slug))
            for index, effect in enumerate(effects):
                if effect.at is None:
                    continue
                if _unreachable(effect.at, run, printed):
                    kept.add((side, slug))
                for step in program.steps:
                    if not _addresses(effect.at, step, side, program, specs):
                        continue
                    triggers = _triggers(effect, step, side, program, specs)
                    if triggers is None:
                        kept.add((side, slug))
                        continue
                    landed[side, slug].setdefault(step, []).extend(triggers)
                    reaches.append(Reach(slug, index, holders[side], step))
    held = _granting({*landed, *kept}, scopes, holders)
    nodes = []
    for side in sorted(scopes, key=list(Side).index):
        for slug in sorted(slug for each, slug in held if each is side):
            nodes.append(
                _node(rules[slug], holders[side], scopes[side][slug], landed[side, slug], program)
            )
    return Attachment(tuple(nodes), tuple(reaches))


def _holders(fielded: Mapping[Side, Fielded]) -> dict[Side, Holder]:
    return {side: Holder(str(side), each.part) for side, each in fielded.items()}


def _core(rules: Mapping[str, Rule]) -> list[str]:
    return sorted(
        slug for slug, rule in rules.items() if rule.category in _PHASES and _effects(rule)
    )


def _effects(rule: Rule) -> tuple[Effect, ...]:
    return () if rule.graph is None else rule.graph.effects


def _grant(
    granted: RuleRef,
    to: Role | WeaponMatch | None,
    via: str,
    side: Side,
    fielded: Mapping[Side, Fielded],
    scopes: Mapping[Side, dict[str, list[tuple[RuleRef, Source]]]],
) -> None:
    match to:
        case Role.THIS_MODEL:
            scopes[side][granted.rule].append((granted, Source(Carrier.EFFECT, via=via)))
        case Role.THE_ENEMY:
            scopes[side.other][granted.rule].append((granted, Source(Carrier.EFFECT, via=via)))
        case WeaponMatch() as target:
            wielded, profile = fielded[side].wielded, fielded[side].weapon
            if wielded is None or profile is None or not _matches(target, wielded):
                return
            source = Source(Carrier.WEAPON, wielded.id, profile.name or wielded.name, via)
            scopes[side][granted.rule].append((granted, source))


def _matches(target: WeaponMatch, wielded: Weapon) -> bool:
    return target.type in (None, wielded.weapon_type) and target.weapon in (None, wielded.id)


def _unreachable(
    at: Address, run: set[StepSequence], printed: set[tuple[StepSequence, str]]
) -> bool:
    sequences = at.sequences
    return any(q in run for q in sequences) and all((q, at.step) not in printed for q in sequences)


def _role(side: Side, spec: Spec) -> Role:
    return Role.THIS_MODEL if spec.side is side else Role.THE_ENEMY


def _addresses(
    at: Address,
    step: Step[Any],
    side: Side,
    program: Program,
    specs: Mapping[Step[Any], Spec],
) -> bool:
    spec = specs[step]
    blocks = program.paths[step].split("/")[:-1]
    return (
        at.step == spec.name
        and spec.sequence in at.sequences
        and at.by is _role(side, spec)
        and (not isinstance(at.in_, Printed) or at.in_ in blocks)
        and (not isinstance(at.not_in, Printed) or at.not_in not in blocks)
    )


def _triggers(
    effect: Effect,
    step: Step[Any],
    side: Side,
    program: Program,
    specs: Mapping[Step[Any], Spec],
) -> tuple[Step[Any], ...] | None:
    read: list[tuple[str, Role | None]] = []
    if effect.when is not None and effect.when.step is not None:
        read.append((effect.when.step, effect.when.by))
    for fact in (*effect.fact_gates, *effect.fact_refs):
        if fact.fact in Printed:
            read.append((fact.fact, fact.of))
    visible = [item for item in reversed(program.visible[step]) if isinstance(item, Step)]
    found = []
    for name, role in read:
        nearest = next(
            (each for each in visible if each.name == name and _role(side, specs[each]) is role),
            None,
        )
        if nearest is None:
            return None
        found.append(nearest)
    return tuple(found)


def _granting(
    held: set[tuple[Side, str]],
    scopes: Mapping[Side, Mapping[str, Carried]],
    holders: Mapping[Side, Holder],
) -> set[tuple[Side, str]]:
    named = {f"{holders[side]}/{slug}": (side, slug) for side in scopes for slug in scopes[side]}
    waiting = list(held)
    while waiting:
        side, slug = waiting.pop()
        for _, source in scopes[side][slug]:
            if source.via is not None and named[source.via] not in held:
                held.add(named[source.via])
                waiting.append(named[source.via])
    return held


def _node(
    rule: Rule,
    holder: Holder,
    carried: Carried,
    landed: Mapping[Step[Any], list[Step[Any]]],
    program: Program,
) -> RuleNode:
    xs = [reference.x for reference, _ in carried if reference.x is not None]
    try:
        x = None if rule.parameter is None else rule.parameter.combined(xs)
    except ValueError as error:
        raise AttachError(f"{rule.id} at {holder}: {error}") from error
    landings = tuple(
        Landing(at, triggers=tuple(sorted(set(landed[at]), key=program.steps.index)))
        for at in sorted(landed, key=program.steps.index)
    )
    return RuleNode(
        rule=rule.id,
        name=rule.display(x),
        holder=holder,
        sources=tuple(source for _, source in carried),
        landings=landings,
        may=rule.graph is not None and rule.graph.may,
    )
