"""Attaching the rules of both fielded sides to a program's steps.

A landing carries the operations its step runs, or holds, carrying none, when
any effect of the node there is one the step cannot run.
"""

from collections import defaultdict
from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

from avelorn.core.errors import AvelornError
from avelorn.core.graph import (
    Carrier,
    Change,
    Contribution,
    Eligibility,
    Holder,
    Landing,
    Program,
    RuleNode,
    Source,
    State,
    Step,
)
from avelorn.core.graph import Operation as GraphOperation
from avelorn.tow.changes import (
    Attacks,
    Check,
    Constant,
    Equals,
    Gate,
    Granted,
    MoreThan,
    Operated,
    Shows,
)
from avelorn.tow.fielding import Fielding
from avelorn.tow.schema.effect import (
    Address,
    Effect,
    FactGate,
    FactRef,
    Gates,
    Operation,
    Role,
    WeaponMatch,
    When,
)
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.step import Step as Printed
from avelorn.tow.schema.step import StepSequence
from avelorn.tow.schema.weapon import Weapon
from avelorn.tow.steps import Spec

type Carried = tuple[tuple[RuleRef, Source], ...]
type Reached = list[tuple[int, Effect, tuple[Step[Any], ...]]]

_PHASES = frozenset(Phase)
_AMENDS = frozenset({Operation.ALLOW, Operation.FORBID})


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
    """The rule nodes of one fielding, with every reach behind their landings.

    ``held`` lists the reaches whose landing carries nothing.
    """

    nodes: tuple[RuleNode, ...]
    reaches: tuple[Reach, ...]
    held: tuple[Reach, ...]


def rules_in_scope(
    holder: Holder, fielded: Mapping[Side, Fielding], rules: Mapping[str, Rule]
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
    fielded: Mapping[Side, Fielding],
    rules: Mapping[str, Rule],
    inputs: Mapping[str, State[Any]],
) -> Attachment:
    """The rule nodes both fielded sides give a program, built and not yet attached.

    ``inputs`` are the program's inputs by name, which fact gates read. The
    attach fails with an :class:`AttachError` on a rule whose sources at one
    holder give X values that do not combine, on a gate comparing a step with a
    value it never outputs, and on a rule with no X carried twice to a landing
    that runs.

    Returns:
        The nodes, ordered by side then slug, every effect that reached a step,
        and the reaches held.
    """
    holders = _holders(fielded)
    scopes = {side: rules_in_scope(holder, fielded, rules) for side, holder in holders.items()}
    fielding = _Fielding(program, specs, fielded, rules, inputs, holders, scopes)
    run = {spec.sequence for spec in specs.values()}
    printed = {spec.key for spec in specs.values()}
    landed: dict[tuple[Side, str], dict[Step[Any], Reached]] = defaultdict(dict)
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
                    triggers = _triggers(effect, step, side, program)
                    if triggers is None:
                        kept.add((side, slug))
                        continue
                    landed[side, slug].setdefault(step, []).append((index, effect, triggers))
                    reaches.append(Reach(slug, index, holders[side], step))
    named = _granting({*landed, *kept}, scopes, holders)
    nodes: list[RuleNode] = []
    held: list[Reach] = []
    for side in sorted(scopes, key=list(Side).index):
        for slug in sorted(slug for each, slug in named if each is side):
            node, holding = fielding.node(rules[slug], side, landed[side, slug])
            nodes.append(node)
            held.extend(holding)
    return Attachment(tuple(nodes), tuple(reaches), tuple(held))


@dataclass(frozen=True)
class _Fielding:
    program: Program
    specs: Mapping[Step[Any], Spec]
    fielded: Mapping[Side, Fielding]
    rules: Mapping[str, Rule]
    inputs: Mapping[str, State[Any]]
    holders: Mapping[Side, Holder]
    scopes: Mapping[Side, Mapping[str, Carried]]

    def node(
        self, rule: Rule, side: Side, landed: Mapping[Step[Any], Reached]
    ) -> tuple[RuleNode, list[Reach]]:
        holder = self.holders[side]
        carried = self.scopes[side][rule.id]
        x = self.x(rule, side)
        landings = []
        held = []
        for at in sorted(landed, key=self.program.steps.index):
            reached = landed[at]
            triggers = {trigger for _, _, each in reached for trigger in each}
            operations = self.operations(rule, side, at, reached)
            if operations is None:
                held.extend(Reach(rule.id, index, holder, at) for index, _, _ in reached)
            contributions, changes = operations or ((), ())
            landings.append(
                Landing(
                    at,
                    contributions=contributions,
                    changes=changes,
                    triggers=tuple(sorted(triggers, key=self.program.steps.index)),
                )
            )
        node = RuleNode(
            rule=rule.id,
            name=rule.display(x),
            holder=holder,
            sources=tuple(source for _, source in carried),
            landings=tuple(landings),
            may=rule.graph is not None and rule.graph.may,
        )
        return node, held

    def x(self, rule: Rule, side: Side) -> int | str | None:
        xs = [
            reference.x for reference, _ in self.scopes[side][rule.id] if reference.x is not None
        ]
        try:
            return None if rule.parameter is None else rule.parameter.combined(xs)
        except ValueError as error:
            raise AttachError(f"{rule.id} at {self.holders[side]}: {error}") from error

    def operations(
        self, rule: Rule, side: Side, at: Step[Any], reached: Reached
    ) -> tuple[tuple[Contribution[Any], ...], tuple[Change, ...]] | None:
        carried = self.scopes[side][rule.id]
        if any(self.gated_grant(rule, source) for _, source in carried):
            return None
        contributions: list[Contribution[Any]] = []
        changes: list[Change] = []
        for _, effect, _ in reached:
            if isinstance(at, Eligibility) and effect.operation in _AMENDS:
                contribution = self.contribution(rule, side, at, effect)
                if contribution is None:
                    return None
                contributions.append(contribution)
                continue
            operated = self.operated(rule, side, at, effect)
            if operated is None:
                return None
            changes.extend(operated)
        if rule.parameter is None and len(carried) > 1:
            raise AttachError(
                f"{rule.id} at {self.holders[side]} has {len(carried)} sources, "
                f"and no X to combine them, at {self.program.paths[at]}"
            )
        return tuple(contributions), tuple(changes)

    def contribution(
        self, rule: Rule, side: Side, at: Step[Any], effect: Effect
    ) -> Contribution[Any] | None:
        named = effect.allow or effect.forbid
        if named is None or effect.limit is not None:
            return None
        gate = self.gate(rule, side, at, effect)
        if gate is None or any(isinstance(check, Attacks) for check in gate.checks):
            return None
        operation = GraphOperation.ALLOW if effect.allow else GraphOperation.FORBID
        return Contribution(
            operation=operation,
            options=partial(_named, frozenset(named), gate),
            text=f"{operation} {', '.join(sorted(named))}",
            inputs=gate.reads,
        )

    def gated_grant(self, rule: Rule, source: Source) -> bool:
        if source.via is None:
            return False
        granter = source.via.rsplit("/", 1)[-1]
        return any(
            effect.grants is not None
            and effect.grants.rule == rule.id
            and (effect.when is not None or effect.unless is not None)
            for effect in _effects(self.rules[granter])
        )

    def operated(
        self, rule: Rule, side: Side, at: Step[Any], effect: Effect
    ) -> list[Operated] | None:
        runs = self.specs[at].runs
        operation = effect.operation
        if effect.limit is not None or not runs:
            return None
        keys: tuple[Any, ...] = (None,)
        match operation:
            case Operation.ADD | Operation.SET:
                keys = tuple(effect.add or effect.set_ or {})
                if not set(keys) <= runs.get(operation, frozenset()):
                    return None
                if effect.of is not None and effect.of is not _role(side, at):
                    return None
            case Operation.REROLL:
                if effect.reroll not in runs.get(operation, frozenset()):
                    return None
            case Operation.MULTIPLY:
                if operation not in runs:
                    return None
            case Operation.CANCELS:
                pass
            case _:
                return None
        if any(isinstance(amount, FactRef) for amount in effect.amounts):
            return None
        multiplies = operation is Operation.MULTIPLY
        if effect.reads_x and not multiplies and not isinstance(self.x(rule, side), int):
            return None
        gate = self.gate(rule, side, at, effect)
        if gate is None:
            return None
        carried = self.scopes[side][rule.id]
        sources = tuple(Granted(reference.x, source.via) for reference, source in carried)
        return [Operated(rule.id, effect, key, gate, sources, rule.parameter) for key in keys]

    def gate(self, rule: Rule, side: Side, at: Step[Any], effect: Effect) -> Gate | None:
        when: list[Check] = []
        if effect.when is not None:
            triggered = self.trigger(rule, side, at, effect.when)
            gated = self.gates(rule, side, at, effect.when)
            if triggered is None or gated is None:
                return None
            when = [*triggered, *gated]
        unless = None
        if effect.unless is not None:
            unless = self.gates(rule, side, at, effect.unless)
            if unless is None:
                return None
        return Gate.folded(tuple(when), None if unless is None else tuple(unless))

    def trigger(self, rule: Rule, side: Side, at: Step[Any], when: When) -> list[Check] | None:
        if when.step is None:
            return []
        step = self.nearest(when.step, when.by, side, at)
        if step is None or when.needed is not None or isinstance(when.is_, FactRef):
            return None
        checks: list[Check] = []
        if when.natural is not None:
            checks.append(Shows(step.key, when.natural))
        if when.is_ is not None:
            checks.append(self.equals(rule, step, when.is_))
        return checks or None

    def gates(self, rule: Rule, side: Side, at: Step[Any], gates: Gates) -> list[Check] | None:
        if gates.worn is not None or gates.carried_by is not None or gates.foe is not None:
            return None
        checks: list[Check] = []
        if gates.with_ is not None:
            wielded = self.fielded[side].hit.wielded
            checks.append(Constant(wielded is not None and _matches(gates.with_, wielded)))
        if gates.attack is not None:
            attack = gates.attack
            for slug, wanted in (
                ("magical-attacks", attack.magical),
                ("flaming-attacks", attack.flaming),
            ):
                if wanted is not None:
                    checks.append(Attacks(self.attacking(slug, at), wanted))
        for fact in gates.facts:
            check = self.fact(rule, side, at, fact)
            if check is None:
                return None
            checks.append(check)
        return checks

    def fact(self, rule: Rule, side: Side, at: Step[Any], fact: FactGate) -> Check | None:
        comparator, value = fact.compared
        if isinstance(value, FactRef):
            return None
        if fact.fact in Printed:
            step = self.nearest(Printed(fact.fact), fact.of, side, at)
            if step is None or comparator != "is":
                return None
            return self.equals(rule, step, value)
        name = str(fact.fact)
        if fact.of is not None:
            name = f"{side if fact.of is Role.THIS_MODEL else side.other}/{name}"
        known = self.inputs.get(name)
        match comparator:
            case "is" if known is not None:
                return Equals(known, value)
            case "more-than" if known is not None and isinstance(value, int):
                return MoreThan(known, value)
        return None

    def equals(self, rule: Rule, step: Step[Any], value: Hashable) -> Equals:
        spec = self.specs[step]
        if spec.outcomes is None or value not in spec.outcomes:
            raise AttachError(
                f"{rule.id} reads {value!r} from {self.program.paths[step]}, "
                f"which outputs {sorted(map(str, spec.outcomes or ())) or 'no listed value'}"
            )
        return Equals(step.key, value)

    def attacking(self, slug: str, at: Step[Any]) -> str | None:
        acting = Side(at.side)
        side = acting if self.specs[at].side is Side.ATTACKER else acting.other
        return f"{self.holders[side]}/{slug}" if slug in self.scopes[side] else None

    def nearest(
        self, name: Printed, role: Role | None, side: Side, at: Step[Any]
    ) -> Step[Any] | None:
        return _nearest(name, role, side, at, self.program)


def _named(
    named: frozenset[str], gate: Gate, printed: frozenset[str], *values: Hashable
) -> frozenset[str]:
    return named if gate.test(values, frozenset()) else frozenset()


def _holders(fielded: Mapping[Side, Fielding]) -> dict[Side, Holder]:
    return {side: Holder(str(side), each.unit) for side, each in fielded.items()}


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
    fielded: Mapping[Side, Fielding],
    scopes: Mapping[Side, dict[str, list[tuple[RuleRef, Source]]]],
) -> None:
    match to:
        case Role.THIS_MODEL:
            scopes[side][granted.rule].append((granted, Source(Carrier.EFFECT, via=via)))
        case Role.THE_ENEMY:
            scopes[side.other][granted.rule].append((granted, Source(Carrier.EFFECT, via=via)))
        case WeaponMatch() as target:
            wielded, profile = fielded[side].hit.wielded, fielded[side].hit.weapon
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


def _role(side: Side, step: Step[Any]) -> Role:
    return Role.THIS_MODEL if step.side == side else Role.THE_ENEMY


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
        and at.by is _role(side, step)
        and (not isinstance(at.in_, Printed) or at.in_ in blocks)
        and (not isinstance(at.not_in, Printed) or at.not_in not in blocks)
    )


def _nearest(
    name: str,
    role: Role | None,
    side: Side,
    at: Step[Any],
    program: Program,
) -> Step[Any] | None:
    visible = [item for item in reversed(program.visible[at]) if isinstance(item, Step)]
    return next(
        (each for each in visible if each.name == name and _role(side, each) is role),
        None,
    )


def _triggers(
    effect: Effect,
    step: Step[Any],
    side: Side,
    program: Program,
) -> tuple[Step[Any], ...] | None:
    read: list[tuple[str, Role | None]] = []
    if effect.when is not None and effect.when.step is not None:
        read.append((effect.when.step, effect.when.by))
    for fact in (*effect.fact_gates, *effect.fact_refs):
        if fact.fact in Printed:
            read.append((fact.fact, fact.of))
    found = []
    for name, role in read:
        nearest = _nearest(name, role, side, step, program)
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
