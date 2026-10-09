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
    Decision,
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
    HasSource,
    Holds,
    MoreThan,
    Operated,
    Shows,
    Sources,
)
from avelorn.tow.fielding import Fielding, Part
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
from avelorn.tow.schema.weapon import Weapon, WeaponProfile
from avelorn.tow.steps import Choice, Spec, weapon_choices

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
    holder, and gives a source whose ``via`` names the granting node. A rule
    that only weapons give grants once per weapon, so what it grants rides
    the same weapons.

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
            riding = _riding(scopes[side][slug])
            for effect in _effects(rules[slug]):
                if effect.grants is not None:
                    _grant(effect.grants, effect.to, via, riding, side, fielded, scopes)
    return {slug: tuple(sources) for slug, sources in scopes[Side(holder.side)].items()}


def attach_rules(
    program: Program,
    specs: Mapping[Step[Any], Spec | Choice],
    fielded: Mapping[Side, Fielding],
    rules: Mapping[str, Rule],
    inputs: Mapping[str, State[Any]],
) -> Attachment:
    """The rule nodes both fielded sides give a program, built and not yet attached.

    ``inputs`` are the program's inputs by name, which fact gates read. Where a
    side chooses its weapon, a rule's sources count together only within one
    option: the model's own sources and those of the weapons it holds.

    Returns:
        The nodes, ordered by side then slug, every effect that reached a step,
        and the reaches held.

    Raises:
        AttachError: a side makes its weapon choice twice, a rule's sources give X
            values that do not combine, a gate compares a step with a value it
            never outputs, or a rule with no X is carried twice to a landing that
            runs.
    """
    holders = _holders(fielded)
    scopes = {side: rules_in_scope(holder, fielded, rules) for side, holder in holders.items()}
    try:
        choices = weapon_choices(specs)
    except ValueError as error:
        raise AttachError(f"{program.name}: {error}") from error
    fielding = _Fielding(program, specs, fielded, rules, inputs, holders, scopes, choices)
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
    specs: Mapping[Step[Any], Spec | Choice]
    fielded: Mapping[Side, Fielding]
    rules: Mapping[str, Rule]
    inputs: Mapping[str, State[Any]]
    holders: Mapping[Side, Holder]
    scopes: Mapping[Side, Mapping[str, Carried]]
    choices: Mapping[Side, Decision[Any]]

    def node(
        self, rule: Rule, side: Side, landed: Mapping[Step[Any], Reached]
    ) -> tuple[RuleNode, list[Reach]]:
        holder = self.holders[side]
        carried = self.scopes[side][rule.id]
        xs = self.xs(rule, side)
        x = None if not xs else xs[0] if len(xs) == 1 else " or ".join(map(str, xs))
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

    def xs(self, rule: Rule, side: Side) -> tuple[int | str, ...]:
        parameter = rule.parameter
        if parameter is None:
            return ()
        sources = self.sources(rule.id, side, self.choices.get(side))
        try:
            combined = (
                parameter.combined([each.x for each in held if each.x is not None])
                for held in sources.options
                if held
            )
            return tuple(dict.fromkeys(combined))
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
            if isinstance(at, Decision) and effect.operation is Operation.BAR:
                barred = self.barred(rule, side, at, effect)
                if barred is None:
                    return None
                contributions.append(barred)
                continue
            operated = self.operated(rule, side, at, effect)
            if operated is None:
                return None
            changes.extend(operated)
        together = self.together(rule, side, at)
        if rule.parameter is None and together > 1:
            raise AttachError(
                f"{rule.id} at {self.holders[side]} has {together} sources in force at once, "
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
        sources = self.sources(rule.id, side, self.choice(side, at))
        if sources.reads:
            gate = Gate((*gate.when, HasSource(sources)), gate.unless)
        operation = GraphOperation.ALLOW if effect.allow else GraphOperation.FORBID
        return Contribution(
            operation=operation,
            options=partial(_named, frozenset(named), gate),
            text=f"{operation} {', '.join(sorted(named))}",
            inputs=gate.reads,
        )

    def barred(
        self, rule: Rule, side: Side, at: Decision[Any], effect: Effect
    ) -> Contribution[Any] | None:
        carriers = self.sources(rule.id, side, at).weapons
        if effect.bar is None or effect.limit is not None or not carriers:
            return None
        gate = self.gate(rule, side, at, effect)
        if gate is None or any(isinstance(check, Attacks) for check in gate.checks):
            return None
        named = frozenset(
            option for option in at.options if effect.bar in option and carriers & option
        )
        return Contribution(
            operation=GraphOperation.FORBID,
            options=partial(_named, named, gate),
            text=f"{GraphOperation.FORBID} {', '.join(sorted(map(str, named)))}",
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
        spec = self.specs[at]
        if not isinstance(spec, Spec):
            return None
        runs = spec.runs
        operation = effect.operation
        if effect.limit is not None or not runs:
            return None
        keys: tuple[Any, ...] = (None,)
        whose = self.whose(side, at, effect.of)
        match operation:
            case Operation.ADD | Operation.SET:
                keys = tuple(effect.add or effect.set_ or {})
                folded = {key if whose is None else (whose, key) for key in keys}
                if not folded <= runs.get(operation, frozenset()):
                    return None
            case Operation.REROLL:
                if effect.reroll not in runs.get(operation, frozenset()):
                    return None
            case Operation.DENY | Operation.MULTIPLY:
                if operation not in runs:
                    return None
            case Operation.CANCELS:
                pass
            case _:
                return None
        if any(isinstance(amount, FactRef) for amount in effect.amounts):
            return None
        multiplies = operation is Operation.MULTIPLY
        whole = all(isinstance(x, int) for x in self.xs(rule, side))
        if effect.reads_x and not multiplies and not whole:
            return None
        gate = self.gate(rule, side, at, effect)
        if gate is None:
            return None
        sources = self.sources(rule.id, side, self.choice(side, at))
        return [
            Operated(rule.id, effect, key, whose, gate, sources, rule.parameter) for key in keys
        ]

    def whose(self, side: Side, at: Step[Any], of: Role | None) -> Side | None:
        if of is None:
            return None
        acting = self.specs[at].side
        return acting if of is _role(side, at) else acting.other

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
        if when.holds is not None:
            checks.append(Holds(step.key, frozenset(when.holds)))
        return checks or None

    def gates(self, rule: Rule, side: Side, at: Step[Any], gates: Gates) -> list[Check] | None:
        if gates.worn is not None or gates.carried_by is not None:
            return None
        checks: list[Check] = []
        if gates.with_ is not None:
            chosen = self.choice(side, at)
            wielded = self.fielded[side].hit.wielded
            if chosen is None:
                checks.append(Constant(wielded is not None and _matches(gates.with_, wielded)))
            elif gates.with_.weapon is None or gates.with_.type is not None:
                return None
            else:
                checks.append(Holds(chosen, frozenset({gates.with_.weapon})))
        if gates.foe is not None:
            foe = gates.foe
            if foe.troop_type is None or foe.army is not None or foe.has is not None:
                return None
            checks.append(Constant(self.fielded[side.other].troop_type in foe.troop_type))
        if gates.attack is not None:
            attack = gates.attack
            for slug, wanted in (
                ("magical-attacks", attack.magical),
                ("flaming-attacks", attack.flaming),
            ):
                if wanted is not None:
                    checks.append(self.attacking(slug, at, wanted))
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
        outcomes = spec.outcomes if isinstance(spec, Spec) else None
        if isinstance(step, Decision):
            outcomes = frozenset(step.options)
        if outcomes is None or value not in outcomes:
            raise AttachError(
                f"{rule.id} reads {value!r} from {self.program.paths[step]}, "
                f"which outputs {sorted(map(str, outcomes or ())) or 'no listed value'}"
            )
        return Equals(step.key, value)

    def attacking(self, slug: str, at: Step[Any], wanted: bool) -> Attacks:
        acting = Side(at.side)
        side = acting if self.specs[at].side is Side.ATTACKER else acting.other
        if slug not in self.scopes[side]:
            return Attacks(None, wanted)
        node = f"{self.holders[side]}/{slug}"
        return Attacks(node, wanted, self.sources(slug, side, self.choice(side, at)))

    def together(self, rule: Rule, side: Side, at: Step[Any]) -> int:
        own = self.choices.get(side)
        decision = own if at is own else self.choice(side, at)
        return self.sources(rule.id, side, decision).at_once()

    def sources(self, slug: str, side: Side, choice: Decision[Any] | None) -> Sources:
        granted = tuple(
            Granted(reference.x, source.via, None if choice is None else _rides(source))
            for reference, source in self.scopes[side][slug]
        )
        return Sources(granted, choice)

    def choice(self, side: Side, at: Step[Any]) -> Decision[Any] | None:
        decision = self.choices.get(side)
        if decision is None or decision not in self.program.visible[at]:
            return None
        return decision

    def nearest(
        self, name: Printed, role: Role | None, side: Side, at: Step[Any]
    ) -> Step[Any] | None:
        return _nearest(name, role, side, at, self.program)


def _named(
    named: frozenset[Hashable], gate: Gate, printed: frozenset[Hashable], *values: Hashable
) -> frozenset[Hashable]:
    return named if gate.test(values, frozenset()) else frozenset()


def _rides(source: Source) -> str | None:
    return source.item if source.carrier is Carrier.WEAPON else None


def _holders(fielded: Mapping[Side, Fielding]) -> dict[Side, Holder]:
    return {side: Holder(str(side), each.unit) for side, each in fielded.items()}


def _core(rules: Mapping[str, Rule]) -> list[str]:
    return sorted(
        slug for slug, rule in rules.items() if rule.category in _PHASES and _effects(rule)
    )


def _effects(rule: Rule) -> tuple[Effect, ...]:
    return () if rule.graph is None else rule.graph.effects


def _riding(carried: list[tuple[RuleRef, Source]]) -> tuple[str, ...]:
    if any(source.carrier is not Carrier.WEAPON for _, source in carried):
        return ()
    return tuple(dict.fromkeys(str(source.item) for _, source in carried))


def _grant(
    granted: RuleRef,
    to: Role | WeaponMatch | None,
    via: str,
    riding: tuple[str, ...],
    side: Side,
    fielded: Mapping[Side, Fielding],
    scopes: Mapping[Side, dict[str, list[tuple[RuleRef, Source]]]],
) -> None:
    match to:
        case Role.THIS_MODEL if riding:
            for weapon in riding:
                source = Source(Carrier.WEAPON, weapon, via=via)
                scopes[side][granted.rule].append((granted, source))
        case Role.THIS_MODEL:
            scopes[side][granted.rule].append((granted, Source(Carrier.EFFECT, via=via)))
        case Role.THE_ENEMY:
            if riding and fielded[side].hit.weapons:
                raise AttachError(
                    f"{via} grants {granted.rule} to the enemy from a weapon the {side} chooses"
                )
            scopes[side.other][granted.rule].append((granted, Source(Carrier.EFFECT, via=via)))
        case WeaponMatch() as target:
            for weapon, profile in _wielded(fielded[side].hit):
                if _matches(target, weapon):
                    source = Source(Carrier.WEAPON, weapon.id, profile.name or weapon.name, via)
                    scopes[side][granted.rule].append((granted, source))


def _wielded(part: Part) -> tuple[tuple[Weapon, WeaponProfile], ...]:
    if part.wielded is not None and part.weapon is not None:
        return ((part.wielded, part.weapon),)
    return tuple(
        (weapon, weapon.combat_profile)
        for weapon in part.weapons
        if weapon.combat_profile is not None
    )


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
    specs: Mapping[Step[Any], Spec | Choice],
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
