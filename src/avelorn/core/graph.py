from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from functools import cached_property, partial
from inspect import signature
from types import MappingProxyType
from typing import Any, ClassVar

from avelorn.core.distribution import Distribution, Kernel, Monoid, Probability
from avelorn.core.errors import AvelornError


class GraphError(AvelornError): ...


class Bearer(StrEnum):
    THIS_MODEL = "this-model"
    THE_ENEMY = "the-enemy"
    CORE = "core"


class Verdict(StrEnum):
    APPLIED = "applied"
    HONOURED = "honoured"
    HELD = "held"
    INAPPLICABLE = "inapplicable"


class Operation(StrEnum):
    ALLOW = "allow"
    FORBID = "forbid"
    FORCE = "force"


class By(StrEnum):
    CHOSEN = "chosen"
    ONLY = "only"
    OTHERWISE = "otherwise"


def _shown(value: object) -> int | str:
    return value if isinstance(value, int) else str(value)


def _itself[T](value: T) -> T:
    return value


def _accepts(function: Callable[..., Any], count: int) -> bool:
    try:
        signature(function).bind(*(None for _ in range(count)))
    except (TypeError, ValueError):
        return False
    return True


@dataclass(frozen=True, eq=False)
class State[T: Hashable]:
    """A fact about the table that no block owns, such as the models a unit has left."""

    name: str


@dataclass(frozen=True, eq=False)
class Tally[T: Hashable]:
    name: str
    counts: Mapping["Repeat", "Projection[T]"]


@dataclass(frozen=True, eq=False)
class Mark[T: Hashable]:
    name: str


type Key = Step[Any] | State[Any] | Tally[Any] | Mark[Any]


@dataclass(frozen=True)
class World:
    """One way things could have gone: the values of the state and of the locals."""

    values: frozenset[tuple[Key, Any]] = frozenset()

    def of[T: Hashable](self, key: "Step[T] | State[T] | Tally[T] | Mark[T]") -> T:
        for held, value in self.values:
            if held is key:
                return value
        raise GraphError(f"{key.name} is not held in this world")

    def holding(self, key: Key, value: Hashable) -> "World":
        kept = {pair for pair in self.values if pair[0] is not key}
        return World(frozenset({*kept, (key, value)}))

    def keeping(self, keys: frozenset[Key]) -> "World":
        return World(frozenset(pair for pair in self.values if pair[0] in keys))


@dataclass(frozen=True)
class Settled:
    world: World
    applied: frozenset[str] = frozenset()

    def verdict(self, rule: str) -> Verdict:
        return Verdict.APPLIED if rule in self.applied else Verdict.HONOURED


@dataclass(frozen=True, eq=False)
class Stack:
    table: Distribution[World] | None
    count: int
    taken: dict["Projection[Any]", Distribution[Any]] = field(default_factory=dict)

    def read[T: Hashable](self, projection: "Projection[T]") -> Distribution[T]:
        held = self.taken.get(projection)
        if held is not None:
            return held
        aggregation = projection.aggregation
        if self.table is None:
            read = Distribution.pure(aggregation.identity)
        else:
            read = self.table.map(projection.of).repeat(self.count, aggregation)
        self.taken[projection] = read
        return read


@dataclass
class Edge:
    stacks: Distribution[Stack]
    stacked: dict["Projection[Any]", Distribution[Any]] = field(default_factory=dict)

    @classmethod
    def single(cls, joint: Distribution[World]) -> "Edge":
        return cls(Distribution.pure(Stack(joint, 1)))

    @property
    def joint(self) -> Distribution[World]:
        tables = [stack.table for stack in self.stacks.mass]
        if len(tables) != 1 or tables[0] is None:
            raise GraphError("an edge inside a group holds a stack per outer world, not one table")
        return tables[0]

    def read[T: Hashable](self, projection: "Projection[T]") -> Distribution[T]:
        held = self.stacked.get(projection)
        if held is not None:
            return held

        def taken(stack: Stack) -> Distribution[T]:
            return stack.read(projection)

        read = self.stacks.bind(taken)
        self.stacked[projection] = read
        return read


@dataclass(frozen=True, eq=False)
class Projection[T: Hashable]:
    label: str
    reads: tuple[Key, ...]
    project: Callable[..., T]
    aggregation: Monoid[T]

    def of(self, world: World) -> T:
        return self.project(*(world.of(source) for source in self.reads))

    def view(self, edge: Edge | None) -> dict[str, Any]:
        read = Distribution[T]({}) if edge is None else edge.read(self)
        outcomes = [{"value": _shown(value), "p": float(p)} for value, p in read.mass.items()]
        return {"label": self.label, "outcomes": outcomes}


@dataclass(frozen=True, eq=False)
class Scalar[T]:
    label: str
    value: T
    reads: ClassVar[tuple[Key, ...]] = ()

    def view(self, edge: Edge | None) -> dict[str, Any]:
        return {"label": self.label, "value": _shown(self.value)}


type Reading = Projection[Any] | Scalar[Any]


@dataclass(frozen=True)
class Modifier:
    rule: str
    move: int

    def view(self) -> dict[str, Any]:
        return {"rule": self.rule, "move": self.move}


@dataclass(frozen=True, eq=False, kw_only=True)
class Step[Out: Hashable](ABC):
    kind: ClassVar[str]
    name: str
    side: str
    inputs: tuple[Key, ...] = ()
    kernel: Kernel[Out] | None = None
    readings: list[Reading] = field(default_factory=list)
    writes: State[Out] | None = None

    @property
    def key(self) -> Key:
        return self if self.writes is None else self.writes

    @abstractmethod
    def settled(self, world: World, lane: "Lane") -> Distribution[Settled]: ...

    def entered(self, world: World, value: Out) -> Settled:
        return Settled(world.holding(self.key, value))

    def output(self, label: str, aggregation: Monoid[Out]) -> Projection[Out]:
        return Projection(label, (self.key,), _itself, aggregation)

    def show(self, reading: Reading) -> None:
        self.readings.append(reading)

    def shown(self) -> tuple[Reading, ...]:
        return tuple(self.readings)

    def drawn(self) -> tuple[Reading, ...]:
        return tuple(self.readings)

    def reads(self) -> frozenset[Key]:
        return frozenset(key for reading in self.shown() for key in reading.reads)

    def arguments(self, world: World) -> tuple[Any, ...]:
        return tuple(world.of(source) for source in self.inputs)

    def needs(self, program: "Program") -> tuple[Key, ...]:
        return self.inputs

    def declare(self, program: "Program", prefix: str, visible: list["Item"]) -> None:
        path = f"{prefix}/{self.name}"
        for source in self.inputs:
            if isinstance(source, Step) and source not in visible:
                raise GraphError(f"{path} inputs {source.name}, which is not in scope")
        if self.kernel is not None and not _accepts(self.kernel, len(self.inputs)):
            raise GraphError(f"{path} kernel cannot accept {len(self.inputs)} positional inputs")
        program.take(self, path)
        program.visible[self] = tuple(visible)
        if self.writes is None:
            visible.append(self)
        reads = self.reads()
        for source in reads:
            if isinstance(source, Step) and source not in visible:
                raise GraphError(f"{path} shows {source.name}, which is not in scope")
        program.reach(path, (*self.inputs, *reads, self.key), visible)

    def collect(self, program: "Program") -> None:
        program.steps.append(self)
        program.readings[self] = self.shown()

    def liveness(self, after: frozenset[Key], program: "Program") -> frozenset[Key]:
        program.live[self] = after
        return ((after | self.reads()) - {self.key}) | set(self.needs(program))

    def run(self, lane: "Lane") -> None:
        def settled(world: World) -> Distribution[Settled]:
            return self.settled(world, lane)

        self.conclude(lane, lane.joint.bind(settled))

    def conclude(self, lane: "Lane", settled: Distribution[Settled]) -> None:
        for rule in dict.fromkeys(each.rule for each in lane.program.amending(self)):
            lane.judged[self, rule] = settled.map(partial(Settled.verdict, rule=rule))
        after = lane.program.live[self]
        held = after | self.reads()

        def kept(each: Settled) -> World:
            return each.world.keeping(held)

        def onward(world: World) -> World:
            return world.keeping(after)

        edge = settled.map(kept)
        lane.edges[self] = Edge.single(edge)
        lane.joint = edge if held <= after else edge.map(onward)

    def detail(self, lane: "Lane", edge: Edge | None) -> dict[str, Any]:
        return {}

    def view(self, paths: Mapping[Any, str], lane: "Lane") -> dict[str, Any]:
        edge = lane.edges.get(self)
        needs = dict.fromkeys(self.needs(lane.program))
        return {
            "path": paths[self],
            "step": self.name,
            "kind": self.kind,
            "side": self.side,
            "inputs": [paths[source] for source in needs if isinstance(source, Step)],
            "ran": edge is not None,
            "edge": {"readings": [reading.view(edge) for reading in self.drawn()]},
            **self.detail(lane, edge),
        }


@dataclass(frozen=True, eq=False, kw_only=True)
class Measurement[Out: Hashable](Step[Out]):
    kind = "measurement"
    kernel: Kernel[Out]

    def settled(self, world: World, lane: "Lane") -> Distribution[Settled]:
        return self.kernel(*self.arguments(world)).map(partial(self.entered, world))


@dataclass(frozen=True, eq=False, kw_only=True)
class Consequence[Out: Hashable](Step[Out]):
    kind = "consequence"
    kernel: Kernel[Out]

    def settled(self, world: World, lane: "Lane") -> Distribution[Settled]:
        return self.kernel(*self.arguments(world)).map(partial(self.entered, world))


@dataclass(frozen=True, eq=False, kw_only=True)
class Roll[Out: Hashable](Step[Out]):
    kind = "roll"
    kernel: Kernel[Out]
    target: Reading

    def settled(self, world: World, lane: "Lane") -> Distribution[Settled]:
        return self.kernel(*self.arguments(world)).map(partial(self.entered, world))

    def shown(self) -> tuple[Reading, ...]:
        return (*self.readings, self.target)

    def detail(self, lane: "Lane", edge: Edge | None) -> dict[str, Any]:
        return {
            "target": self.target.view(edge),
            "modifiers": [modifier.view() for modifier in lane.program.modifiers.get(self, ())],
        }


@dataclass(frozen=True, eq=False, kw_only=True)
class Contribution[O: Hashable]:
    operation: Operation
    options: Callable[..., frozenset[O]]
    inputs: tuple[Key, ...] = ()

    def names(self, printed: frozenset[O], world: World) -> frozenset[O]:
        return self.options(printed, *(world.of(source) for source in self.inputs))


@dataclass(frozen=True)
class Amendment:
    rule: str
    contribution: Contribution[Any]


@dataclass(frozen=True, eq=False, kw_only=True)
class Amended[O: Hashable, Out: Hashable](Step[Out], ABC):
    def needs(self, program: "Program") -> tuple[Key, ...]:
        amendments = program.amending(self)
        return (*self.inputs, *(key for each in amendments for key in each.contribution.inputs))

    def check(self, path: str, named: frozenset[O]) -> None:
        return None

    def settle(
        self, printed: frozenset[O], world: World, lane: "Lane"
    ) -> tuple[frozenset[O], frozenset[str]]:
        path = lane.program.paths[self]
        allowed, forbidden, forced, applied = set(printed), set[O](), set[O](), set[str]()
        for each in lane.program.amending(self):
            if lane.declined(each.rule):
                continue
            named = each.contribution.names(printed, world)
            self.check(path, named)
            if named:
                applied.add(each.rule)
            match each.contribution.operation:
                case Operation.ALLOW:
                    allowed |= named
                case Operation.FORBID:
                    forbidden |= named
                case Operation.FORCE:
                    forced |= named
        allowed -= forbidden
        narrowed = allowed & forced
        return frozenset(narrowed or allowed), frozenset(applied)


@dataclass(frozen=True, eq=False, kw_only=True)
class Eligibility[O: Hashable](Amended[O, frozenset[O]]):
    kind = "measurement"
    kernel: Kernel[frozenset[O]]

    def settled(self, world: World, lane: "Lane") -> Distribution[Settled]:
        def amended(printed: frozenset[O]) -> Settled:
            allowed, applied = self.settle(printed, world, lane)
            return Settled(world.holding(self.key, allowed), applied)

        return self.kernel(*self.arguments(world)).map(amended)


@dataclass(frozen=True)
class Taken[O: Hashable]:
    option: O
    by: By

    def __str__(self) -> str:
        return f"{self.option} ({self.by})"


class _Fork(Exception):
    def __init__(self, decision: "Decision[Any]", options: tuple[Any, ...]) -> None:
        super().__init__(decision.name)
        self.decision = decision
        self.options = options


@dataclass(frozen=True, eq=False, kw_only=True)
class Decision[Out: Hashable](Amended[Out, Out]):
    kind = "decision"
    options: Mapping[Out, tuple["Item", ...]]
    otherwise: Out
    closed: frozenset[Out] = frozenset()

    @cached_property
    def how(self) -> Mark[Taken[Out]]:
        return Mark(self.name)

    @cached_property
    def taken(self) -> Projection[Taken[Out]]:
        return Projection(
            "taken", (self.how,), _itself, Monoid(Taken(self.otherwise, By.OTHERWISE))
        )

    @property
    def printed(self) -> frozenset[Out]:
        return frozenset(self.options) - self.closed

    def shown(self) -> tuple[Reading, ...]:
        return (*self.readings, self.taken)

    def drawn(self) -> tuple[Reading, ...]:
        return self.shown()

    def declare(self, program: "Program", prefix: str, visible: list["Item"]) -> None:
        path = f"{prefix}/{self.name}"
        if self.writes is not None:
            raise GraphError(f"{path} writes {self.writes.name}, but a decision holds its option")
        for printed in (self.otherwise, *self.closed):
            if printed not in self.options:
                raise GraphError(f"{path} names {printed!r}, which is not one of its options")
        super().declare(program, prefix, visible)
        bodies: dict[Any, Body] = {}
        for option, items in self.options.items():
            body = Body(name=str(option), items=items, decision=self, option=option)
            body.declare(program, path, visible)
            bodies[option] = body
        program.bodies[self] = bodies

    def collect(self, program: "Program") -> None:
        super().collect(program)
        program.decisions.append(self)

    def check(self, path: str, named: frozenset[Out]) -> None:
        stray = named - set(self.options)
        if stray:
            raise GraphError(f"{path} is offered {sorted(map(str, stray))}, not among its options")

    def take(self, allowed: frozenset[Out], lane: "Lane") -> Taken[Out]:
        if self in lane.choices and lane.choices[self] in allowed:
            return Taken(lane.choices[self], By.CHOSEN)
        if len(allowed) == 1:
            return Taken(next(iter(allowed)), By.ONLY)
        return Taken(self.otherwise, By.OTHERWISE)

    def settled(self, world: World, lane: "Lane") -> Distribution[Settled]:
        allowed, applied = self.settle(self.printed, world, lane)
        taken = self.take(allowed, lane)
        entered = world.holding(self, taken.option).holding(self.how, taken)
        return Distribution.pure(Settled(entered, applied))

    def choose(self, lane: "Lane") -> None:
        if self in lane.given:
            lane.choices[self] = lane.given[self]
            return
        open_options: set[Out] = set()
        for world in lane.joint.mass:
            allowed, _ = self.settle(self.printed, world, lane)
            if len(allowed) > 1:
                open_options |= allowed
        if open_options:
            raise _Fork(self, tuple(option for option in self.options if option in open_options))

    def liveness(self, after: frozenset[Key], program: "Program") -> frozenset[Key]:
        program.exits[self] = after
        entries = frozenset[Key]()
        for body in program.bodies[self].values():
            entries |= body.liveness(after, program)
        return super().liveness(entries | {self.key}, program) - {self.how}

    def run(self, lane: "Lane") -> None:
        self.choose(lane)
        super().run(lane)

        def option(world: World) -> Out:
            return world.of(self)

        def onward(world: World) -> World:
            return world.keeping(after)

        resolved = lane.joint
        weights = resolved.map(option)
        bodies = lane.program.bodies[self]
        ran = {
            each: self.branch(lane, bodies[each], resolved, weight)
            for each, weight in weights.mass.items()
        }
        after = lane.program.exits[self]
        lane.joint = weights.bind(ran.__getitem__).map(onward)

    def branch(
        self, lane: "Lane", body: "Body", resolved: Distribution[World], weight: Probability
    ) -> Distribution[World]:
        entry = lane.program.entries[body]

        def opened(world: World) -> World:
            return world.keeping(entry)

        within = {
            world: p / weight
            for world, p in resolved.mass.items()
            if world.of(self) == body.option
        }
        lane.joint = Distribution(within).map(opened)
        body.run(lane)
        return lane.joint

    def detail(self, lane: "Lane", edge: Edge | None) -> dict[str, Any]:
        return {"options": [str(option) for option in self.options]}


@dataclass(frozen=True, eq=False, kw_only=True)
class May(Decision[bool]):
    options: Mapping[bool, tuple["Item", ...]] = field(
        default_factory=lambda: MappingProxyType({True: (), False: ()})
    )
    otherwise: bool = False


type Item = Step[Any] | Block


@dataclass(frozen=True, eq=False, kw_only=True)
class Block(ABC):
    kind: ClassVar[str]
    scoped: ClassVar[bool] = True
    name: str
    items: tuple[Item, ...]

    def declare(self, program: "Program", prefix: str, visible: list[Item]) -> None:
        path = f"{prefix}/{self.name}"
        self.check(path, visible)
        program.take(self, path)
        inner = list(visible) if self.scoped else visible
        for item in self.items:
            item.declare(program, path, inner)

    def check(self, path: str, visible: list[Item]) -> None:
        return None

    def collect(self, program: "Program") -> None:
        program.blocks.append(self)

    def liveness(self, after: frozenset[Key], program: "Program") -> frozenset[Key]:
        for item in reversed(self.items):
            after = item.liveness(after, program)
        program.entries[self] = after
        return after

    def run(self, lane: "Lane") -> None:
        for item in self.items:
            item.run(lane)

    @abstractmethod
    def detail(self, paths: Mapping[Any, str]) -> dict[str, Any]: ...

    def view(self, paths: Mapping[Any, str]) -> dict[str, Any]:
        return {"path": paths[self], "kind": self.kind, **self.detail(paths)}


@dataclass(frozen=True, eq=False, kw_only=True)
class Group(Block, ABC):
    kind = "group"


@dataclass(frozen=True, eq=False, kw_only=True)
class Sequence(Group):
    kind = "sequence"
    scoped = False
    collapsed: bool = False

    def detail(self, paths: Mapping[Any, str]) -> dict[str, Any]:
        return {"collapsed": self.collapsed}


@dataclass(frozen=True, eq=False, kw_only=True)
class Repeat(Group):
    """Runs its items for one attack; the outer worlds resume at its exit, cut to what is live."""

    kind = "repeat"
    times: Step[int]
    collapsed: bool = False

    def declare(self, program: "Program", prefix: str, visible: list[Item]) -> None:
        first_step, first_block = len(program.steps), len(program.blocks)
        super().declare(program, prefix, visible)
        path = program.paths[self]
        for block in program.blocks[first_block + 1 :]:
            if isinstance(block, Repeat):
                raise GraphError(f"{program.paths[block]} repeats inside {path}")
        inside = program.steps[first_step:]
        for step in inside:
            if isinstance(step, Amended):
                raise GraphError(f"{program.paths[step]} settles options inside {path}")
            if step.writes is not None:
                raise GraphError(
                    f"{program.paths[step]} writes {step.writes.name} inside a repeat, "
                    "which cannot carry state out"
                )
        program.inside[self] = frozenset(inside)
        visible.append(self)

    def check(self, path: str, visible: list[Item]) -> None:
        if self.times not in visible:
            raise GraphError(f"{path} runs {self.times.name} times, which is not in scope")

    def liveness(self, after: frozenset[Key], program: "Program") -> frozenset[Key]:
        program.live[self] = after
        tally = program.tallies.get(self)
        counted = frozenset() if tally is None else frozenset(tally.counts[self].reads)
        body = super().liveness(counted, program)
        if tally is not None and program.seeds[tally] is self:
            after = after - {tally}
        return after | body | {self.times}

    def run(self, lane: "Lane") -> None:
        program = lane.program
        body = program.entries[self]
        counts = {world: world.of(self.times) for world in lane.joint.mass}
        opened = {world: world.keeping(body) for world in counts}
        ran: dict[World, Lane] = {}
        for world, count in counts.items():
            start = opened[world]
            if count > 0 and start not in ran:
                inner = Lane(program=program, given=lane.given, joint=Distribution.pure(start))
                super().run(inner)
                ran[start] = inner
        for step in program.inside[self]:
            tables = {start: inner.edges[step].joint for start, inner in ran.items()}
            lane.edges[step] = Edge(lane.joint.map(self.stacker(counts, opened, tables)))
        tables = {start: inner.joint for start, inner in ran.items()}
        lane.joint = lane.joint.bind(self.exit(program, self.stacker(counts, opened, tables)))

    def stacker(
        self,
        counts: Mapping[World, int],
        opened: Mapping[World, World],
        tables: Mapping[World, Distribution[World]],
    ) -> Callable[[World], Stack]:
        stacks: dict[tuple[World, int], Stack] = {}
        empty = Stack(None, 0)

        def stack(world: World) -> Stack:
            count = counts[world]
            if count == 0:
                return empty
            start = opened[world]
            made = stacks.get((start, count))
            if made is None:
                made = stacks[start, count] = Stack(tables[start], count)
            return made

        return stack

    def exit(self, program: "Program", stack: Callable[[World], Stack]) -> Kernel[World]:
        after = program.live[self]
        tally = program.tallies.get(self)
        if tally is None:

            def resumed(world: World) -> Distribution[World]:
                return Distribution.pure(world.keeping(after))

            return resumed
        projection = tally.counts[self]
        aggregation = projection.aggregation
        seeds = program.seeds[tally] is self

        def tallied(world: World) -> Distribution[World]:
            prior = aggregation.identity if seeds else world.of(tally)

            def summed(count: Hashable) -> World:
                total = aggregation.operation(prior, count)
                return world.holding(tally, total).keeping(after)

            return stack(world).read(projection).map(summed)

        return tallied

    def detail(self, paths: Mapping[Any, str]) -> dict[str, Any]:
        return {"times": paths[self.times], "collapsed": self.collapsed}


@dataclass(frozen=True, eq=False, kw_only=True)
class Slot(Block):
    kind = "slot"
    scoped = False

    def detail(self, paths: Mapping[Any, str]) -> dict[str, Any]:
        return {"empty": not self.items}


@dataclass(frozen=True, eq=False, kw_only=True)
class Body(Block):
    kind = "body"
    decision: Decision[Any]
    option: Hashable

    def detail(self, paths: Mapping[Any, str]) -> dict[str, Any]:
        return {"decision": paths[self.decision]}


@dataclass(frozen=True)
class Landing:
    at: Step[Any]
    contributions: tuple[Contribution[Any], ...] = ()
    moves: tuple[int, ...] = ()

    def view(self, paths: Mapping[Any, str], rule: str, lane: "Lane") -> dict[str, Any]:
        verdicts = []
        if self.at in lane.edges:
            read = lane.verdicts(rule, self.at).mass
            verdicts = [
                {"verdict": verdict.value, "p": float(read[verdict])}
                for verdict in Verdict
                if verdict in read
            ]
        return {"at": paths[self.at], "verdicts": verdicts}


@dataclass(frozen=True)
class RuleNode:
    rule: str
    name: str
    bearer: Bearer
    landings: tuple[Landing, ...] = ()
    may: bool = False

    def view(self, paths: Mapping[Any, str], lane: "Lane") -> dict[str, Any]:
        return {
            "rule": self.rule,
            "name": self.name,
            "bearer": self.bearer.value,
            "landings": [landing.view(paths, self.rule, lane) for landing in self.landings],
        }


@dataclass
class Program:
    name: str
    sides: tuple[str, ...]
    items: tuple[Item, ...]
    paths: dict[Any, str] = field(default_factory=dict)
    steps: list[Step[Any]] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    decisions: list[Decision[Any]] = field(default_factory=list)
    rules: list[RuleNode] = field(default_factory=list)
    toggles: dict[str, May] = field(default_factory=dict)
    amendments: dict[Step[Any], list[Amendment]] = field(default_factory=dict)
    modifiers: dict[Step[Any], list[Modifier]] = field(default_factory=dict)
    states: list[State[Any]] = field(default_factory=list)
    readings: dict[Step[Any], tuple[Reading, ...]] = field(default_factory=dict)
    visible: dict[Step[Any], tuple[Item, ...]] = field(default_factory=dict)
    live: dict[Item, frozenset[Key]] = field(default_factory=dict)
    inside: dict[Repeat, frozenset[Step[Any]]] = field(default_factory=dict)
    entries: dict[Block, frozenset[Key]] = field(default_factory=dict)
    bodies: dict[Decision[Any], dict[Any, Body]] = field(default_factory=dict)
    exits: dict[Decision[Any], frozenset[Key]] = field(default_factory=dict)
    tallies: dict[Repeat, Tally[Any]] = field(default_factory=dict)
    seeds: dict[Tally[Any], Repeat] = field(default_factory=dict)
    entry: frozenset[Key] = frozenset()

    @classmethod
    def build(cls, name: str, sides: tuple[str, ...], items: tuple[Item, ...]) -> "Program":
        program = cls(name=name, sides=sides, items=items)
        visible: list[Item] = []
        for item in items:
            item.declare(program, name, visible)
        for step in program.steps:
            if step.side not in sides:
                raise GraphError(f"{program.paths[step]} acts for {step.side}, no side of {name}")
        program.settle_liveness()
        return program

    def settle_liveness(self) -> None:
        needed: frozenset[Key] = frozenset()
        for item in reversed(self.items):
            needed = item.liveness(needed, self)
        for toggle in reversed(self.toggles.values()):
            needed = toggle.liveness(needed, self)
        self.entry = needed

    def take(self, item: Item, path: str) -> None:
        if path in self.paths.values():
            raise GraphError(f"{path} is declared twice")
        self.paths[item] = path
        item.collect(self)

    def hold(self, state: State[Any]) -> None:
        if state in self.states:
            return
        path = f"{self.name}/state/{state.name}"
        if path in self.paths.values():
            raise GraphError(f"{path} is declared twice")
        self.paths[state] = path
        self.states.append(state)

    def reach(self, path: str, keys: tuple[Key, ...], visible: list[Item]) -> None:
        for key in keys:
            if isinstance(key, State):
                self.hold(key)
            if isinstance(key, Tally):
                self.count(key, path, visible)

    def count(self, tally: Tally[Any], path: str, visible: list[Item]) -> None:
        groups = list(tally.counts)
        if not groups:
            raise GraphError(f"{tally.name} counts no group")
        for group in groups:
            if group not in visible:
                raise GraphError(f"{path} tallies {group.name}, which is not in scope")
        if tally in self.seeds:
            return
        blocks = {self.paths[group].rsplit("/", 1)[0] for group in groups}
        if len(blocks) != 1:
            raise GraphError(f"{tally.name} sums groups from {', '.join(sorted(blocks))}")
        aggregations = {projection.aggregation for projection in tally.counts.values()}
        if len(aggregations) != 1:
            raise GraphError(f"{tally.name} sums its groups with different aggregations")
        for group, projection in tally.counts.items():
            if group in self.tallies:
                raise GraphError(f"{group.name} is tallied by {self.tallies[group].name} already")
            for source in projection.reads:
                if isinstance(source, Step) and source not in self.inside[group]:
                    raise GraphError(f"{tally.name} counts {source.name}, outside {group.name}")
            self.tallies[group] = tally
        self.seeds[tally] = min(groups, key=self.blocks.index)

    def amending(self, step: Step[Any]) -> tuple[Amendment, ...]:
        return tuple(self.amendments.get(step, ()))

    def attach(self, rule: RuleNode) -> None:
        if any(attached.rule == rule.rule for attached in self.rules):
            raise GraphError(f"{rule.rule} is attached to {self.name} twice")
        if rule.may and rule.bearer is Bearer.CORE:
            raise GraphError(f"{rule.rule} is a core rule, which no player may decline")
        for landing in rule.landings:
            self.check_landing(rule.rule, landing)
        if rule.may:
            toggle = May(name=rule.rule, side=str(rule.bearer))
            toggle.declare(self, f"{self.name}/may", [])
            self.toggles[rule.rule] = toggle
        for landing in rule.landings:
            path = self.paths[landing.at]
            for contribution in landing.contributions:
                self.reach(path, contribution.inputs, list(self.visible[landing.at]))
                self.amendments.setdefault(landing.at, []).append(
                    Amendment(rule.rule, contribution)
                )
            for move in landing.moves:
                self.modifiers.setdefault(landing.at, []).append(Modifier(rule.rule, move))
        self.rules.append(rule)
        self.settle_liveness()

    def check_landing(self, rule: str, landing: Landing) -> None:
        at = landing.at
        if at not in self.paths:
            raise GraphError(f"{rule} lands on {at.name}, which is not declared")
        path = self.paths[at]
        if landing.contributions and not isinstance(at, Amended):
            raise GraphError(f"{rule} amends {path}, which settles no options")
        if landing.moves and not isinstance(at, Roll):
            raise GraphError(f"{rule} moves {path}, which rolls nothing")
        for contribution in landing.contributions:
            if isinstance(at, Eligibility) and contribution.operation is Operation.FORCE:
                raise GraphError(f"{rule} forces {path}, which only allow and forbid edit")
            count = len(contribution.inputs)
            if not _accepts(contribution.options, 1 + count):
                raise GraphError(f"{rule} at {path} cannot accept the options and {count} inputs")
            for source in contribution.inputs:
                if isinstance(source, Step) and source not in self.visible[at]:
                    raise GraphError(f"{rule} at {path} reads {source.name}, not in scope")

    def evaluate(
        self,
        choices: Mapping[Decision[Any], Any] = MappingProxyType({}),
        state: Mapping[State[Any], Hashable] = MappingProxyType({}),
    ) -> tuple["Lane", ...]:
        for fact in state:
            if fact not in self.states:
                raise GraphError(f"{fact.name} is not a state fact of {self.name}")
        for fact in self.states:
            if fact in self.entry and fact not in state:
                raise GraphError(
                    f"{self.name} reads {fact.name} before writing it, so needs it given"
                )
        start = World(frozenset((fact, state[fact]) for fact in self.states if fact in self.entry))
        for step in self.steps:
            if step.shown() != self.readings[step]:
                raise GraphError(f"{self.paths[step]} was shown a reading after build")
        for decision, choice in choices.items():
            if decision not in self.decisions:
                raise GraphError(f"{decision.name} is not a decision in {self.name}")
            if choice not in decision.options:
                raise GraphError(f"{choice!r} is not an option for {decision.name}")
        return self._grow(choices, start)

    def _grow(self, given: Mapping[Decision[Any], Any], start: World) -> tuple["Lane", ...]:
        lane = Lane(program=self, given=given, joint=Distribution.pure(start))
        try:
            for toggle in self.toggles.values():
                toggle.run(lane)
            for item in self.items:
                item.run(lane)
        except _Fork as fork:
            return tuple(
                grown
                for option in fork.options
                for grown in self._grow({**given, fork.decision: option}, start)
            )
        return (lane,)


@dataclass
class Lane:
    program: Program
    given: Mapping[Decision[Any], Any]
    joint: Distribution[World]
    choices: dict[Decision[Any], Any] = field(default_factory=dict)
    edges: dict[Step[Any], Edge] = field(default_factory=dict)
    judged: dict[tuple[Step[Any], str], Distribution[Verdict]] = field(default_factory=dict)

    def declined(self, rule: str) -> bool:
        toggle = self.program.toggles.get(rule)
        return toggle is not None and not self.choices[toggle]

    def verdicts(self, rule: str, at: Step[Any]) -> Distribution[Verdict]:
        if at not in self.edges:
            raise GraphError(f"{self.program.paths[at]} did not run in this lane")
        if any(each.rule == rule for each in self.program.amending(at)):
            return self.judged[at, rule]
        if any(each.rule == rule for each in self.program.modifiers.get(at, ())):
            return Distribution.pure(Verdict.HONOURED if self.declined(rule) else Verdict.APPLIED)
        return Distribution.pure(Verdict.HELD)

    def read[T: Hashable](self, step: Step[Any], projection: Projection[T]) -> Distribution[T]:
        if projection not in self.program.readings[step]:
            raise GraphError(f"{projection.label} is not a reading of {step.name}")
        if step not in self.edges:
            raise GraphError(f"{self.program.paths[step]} did not run in this lane")
        return self.edges[step].read(projection)

    def to_view(self) -> dict[str, Any]:
        paths = self.program.paths
        return {
            "program": self.program.name,
            "sides": list(self.program.sides),
            "nodes": [step.view(paths, self) for step in self.program.steps],
            "blocks": [block.view(paths) for block in self.program.blocks],
            "rules": [rule.view(paths, self) for rule in self.program.rules],
            "lanes": [
                {"decision": paths[decision], "outcome": str(outcome)}
                for decision, outcome in self.choices.items()
            ],
        }
