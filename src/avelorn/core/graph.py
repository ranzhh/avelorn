from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from inspect import signature
from itertools import product
from types import MappingProxyType
from typing import Any, ClassVar

from avelorn.core.distribution import Distribution, Kernel, Monoid
from avelorn.core.errors import AvelornError


class GraphError(AvelornError): ...


class Side(StrEnum):
    THIS_MODEL = "this-model"
    THE_ENEMY = "the-enemy"


class Bearer(StrEnum):
    THIS_MODEL = "this-model"
    THE_ENEMY = "the-enemy"
    CORE = "core"


class Verdict(StrEnum):
    APPLIED = "applied"
    HONOURED = "honoured"
    HELD = "held"
    INAPPLICABLE = "inapplicable"


def _shown(value: object) -> int | str:
    return value if isinstance(value, int) else str(value)


@dataclass(frozen=True, eq=False)
class State[T: Hashable]:
    """A fact about the table that no block owns, such as the models a unit has left."""

    name: str


@dataclass(frozen=True, eq=False)
class Tally[T: Hashable]:
    name: str
    counts: Mapping["Repeat", "Projection[T]"]


type Key = Step[Any] | State[Any] | Tally[Any]


@dataclass(frozen=True)
class World:
    """One way things could have gone: the values of the state and of the locals."""

    values: frozenset[tuple[Key, Any]] = frozenset()

    def of[T: Hashable](self, key: "Step[T] | State[T] | Tally[T]") -> T:
        for held, value in self.values:
            if held is key:
                return value
        raise GraphError(f"{key.name} is not held in this world")

    def holding(self, key: Key, value: Hashable) -> "World":
        kept = {pair for pair in self.values if pair[0] is not key}
        return World(frozenset({*kept, (key, value)}))

    def keeping(self, keys: frozenset[Key]) -> "World":
        return World(frozenset(pair for pair in self.values if pair[0] in keys))


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

    def view(self, edge: Edge) -> dict[str, Any]:
        read = edge.read(self)
        outcomes = [{"value": _shown(value), "p": float(p)} for value, p in read.mass.items()]
        return {"label": self.label, "outcomes": outcomes}


@dataclass(frozen=True, eq=False)
class Scalar[T]:
    label: str
    value: T
    reads: ClassVar[tuple[Key, ...]] = ()

    def view(self, edge: Edge) -> dict[str, Any]:
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
    side: Side
    inputs: tuple[Key, ...] = ()
    kernel: Kernel[Out] | None = None
    readings: list[Reading] = field(default_factory=list)
    writes: State[Out] | None = None

    @property
    def key(self) -> Key:
        return self if self.writes is None else self.writes

    @abstractmethod
    def outcomes(self, world: World, lane: "Lane") -> Distribution[Out]: ...

    def output(self, label: str, aggregation: Monoid[Out]) -> Projection[Out]:
        def project(value: Out) -> Out:
            return value

        return Projection(label, (self.key,), project, aggregation)

    def show(self, reading: Reading) -> None:
        self.readings.append(reading)

    def shown(self) -> tuple[Reading, ...]:
        return tuple(self.readings)

    def reads(self) -> frozenset[Key]:
        return frozenset(key for reading in self.shown() for key in reading.reads)

    def arguments(self, world: World) -> tuple[Any, ...]:
        return tuple(world.of(source) for source in self.inputs)

    def declare(self, program: "Program", prefix: str, visible: list["Item"]) -> None:
        path = f"{prefix}/{self.name}"
        for source in self.inputs:
            if isinstance(source, Step) and source not in visible:
                raise GraphError(f"{path} inputs {source.name}, which is not in scope")
        if self.kernel is not None:
            try:
                signature(self.kernel).bind(*(None for _ in self.inputs))
            except (TypeError, ValueError) as error:
                raise GraphError(
                    f"{path} kernel cannot accept {len(self.inputs)} positional inputs"
                ) from error
        program.take(self, path)
        if self.writes is None:
            visible.append(self)
        reads = self.reads()
        for source in reads:
            if isinstance(source, Step) and source not in visible:
                raise GraphError(f"{path} shows {source.name}, which is not in scope")
        for key in (*self.inputs, *reads, self.key):
            if isinstance(key, State):
                program.hold(key)
            if isinstance(key, Tally):
                program.count(key, path, visible)

    def collect(self, program: "Program") -> None:
        program.steps.append(self)
        program.readings[self] = self.shown()

    def liveness(self, after: frozenset[Key], program: "Program") -> frozenset[Key]:
        program.live[self] = after
        return ((after | self.reads()) - {self.key}) | set(self.inputs)

    def run(self, lane: "Lane") -> None:
        after = lane.program.live[self]
        held = after | self.reads()

        def advance(world: World) -> Distribution[World]:
            def attach(value: Out) -> World:
                return world.holding(self.key, value).keeping(held)

            return self.outcomes(world, lane).map(attach)

        def onward(world: World) -> World:
            return world.keeping(after)

        edge = lane.joint.bind(advance)
        lane.edges[self] = Edge.single(edge)
        lane.joint = edge if held <= after else edge.map(onward)

    def detail(self, edge: Edge) -> dict[str, Any]:
        return {}

    def view(self, paths: Mapping[Any, str], edge: Edge) -> dict[str, Any]:
        return {
            "path": paths[self],
            "step": self.name,
            "kind": self.kind,
            "side": self.side.value,
            "inputs": [paths[source] for source in self.inputs if isinstance(source, Step)],
            "edge": {"readings": [reading.view(edge) for reading in self.readings]},
            **self.detail(edge),
        }


@dataclass(frozen=True, eq=False, kw_only=True)
class Measurement[Out: Hashable](Step[Out]):
    kind = "measurement"
    kernel: Kernel[Out]

    def outcomes(self, world: World, lane: "Lane") -> Distribution[Out]:
        return self.kernel(*self.arguments(world))


@dataclass(frozen=True, eq=False, kw_only=True)
class Consequence[Out: Hashable](Step[Out]):
    kind = "consequence"
    kernel: Kernel[Out]

    def outcomes(self, world: World, lane: "Lane") -> Distribution[Out]:
        return self.kernel(*self.arguments(world))


@dataclass(frozen=True, eq=False, kw_only=True)
class Roll[Out: Hashable](Step[Out]):
    kind = "roll"
    kernel: Kernel[Out]
    target: Reading
    modifiers: tuple[Modifier, ...] = ()

    def outcomes(self, world: World, lane: "Lane") -> Distribution[Out]:
        return self.kernel(*self.arguments(world))

    def shown(self) -> tuple[Reading, ...]:
        return (*self.readings, self.target)

    def detail(self, edge: Edge) -> dict[str, Any]:
        return {
            "target": self.target.view(edge),
            "modifiers": [modifier.view() for modifier in self.modifiers],
        }


@dataclass(frozen=True, eq=False, kw_only=True)
class Decision[Out: Hashable](Step[Out]):
    kind = "decision"
    options: tuple[Out, ...]

    def outcomes(self, world: World, lane: "Lane") -> Distribution[Out]:
        return Distribution.pure(lane.choices[self])

    def collect(self, program: "Program") -> None:
        super().collect(program)
        program.decisions.append(self)

    def detail(self, edge: Edge) -> dict[str, Any]:
        return {"options": [str(option) for option in self.options]}


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
        program.entries[self] = body
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
                inner = Lane(program=program, choices=lane.choices, joint=Distribution.pure(start))
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
class Lanes(Block):
    kind = "lanes"
    decision: Decision[Any]

    def check(self, path: str, visible: list[Item]) -> None:
        if self.decision not in visible:
            raise GraphError(f"{path} splits on {self.decision.name}, which is not in scope")

    def detail(self, paths: Mapping[Any, str]) -> dict[str, Any]:
        return {"decision": paths[self.decision]}


@dataclass(frozen=True)
class Landing:
    at: Step[Any]
    verdict: Verdict

    def view(self, paths: Mapping[Any, str]) -> dict[str, Any]:
        return {"at": paths[self.at], "verdict": self.verdict.value}


@dataclass(frozen=True)
class RuleNode:
    rule: str
    name: str
    bearer: Bearer
    landings: tuple[Landing, ...] = ()

    def view(self, paths: Mapping[Any, str]) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "name": self.name,
            "bearer": self.bearer.value,
            "landings": [landing.view(paths) for landing in self.landings],
        }


@dataclass
class Program:
    name: str
    sides: Mapping[Side, str]
    items: tuple[Item, ...]
    paths: dict[Any, str] = field(default_factory=dict)
    steps: list[Step[Any]] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    decisions: list[Decision[Any]] = field(default_factory=list)
    rules: list[RuleNode] = field(default_factory=list)
    states: list[State[Any]] = field(default_factory=list)
    readings: dict[Step[Any], tuple[Reading, ...]] = field(default_factory=dict)
    live: dict[Item, frozenset[Key]] = field(default_factory=dict)
    inside: dict[Repeat, frozenset[Step[Any]]] = field(default_factory=dict)
    entries: dict[Repeat, frozenset[Key]] = field(default_factory=dict)
    tallies: dict[Repeat, Tally[Any]] = field(default_factory=dict)
    seeds: dict[Tally[Any], Repeat] = field(default_factory=dict)
    entry: frozenset[Key] = frozenset()

    @classmethod
    def build(cls, name: str, sides: Mapping[Side, str], items: tuple[Item, ...]) -> "Program":
        program = cls(name=name, sides=sides, items=items)
        visible: list[Item] = []
        for item in items:
            item.declare(program, name, visible)
        needed: frozenset[Key] = frozenset()
        for item in reversed(items):
            needed = item.liveness(needed, program)
        program.entry = needed
        return program

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

    def attach(self, rule: RuleNode) -> None:
        for landing in rule.landings:
            if landing.at not in self.paths:
                raise GraphError(f"{rule.rule} lands on {landing.at.name}, which is not declared")
        self.rules.append(rule)

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
        open_options = [
            (choices[decision],) if decision in choices else decision.options
            for decision in self.decisions
        ]
        return tuple(
            self._lane(dict(zip(self.decisions, taken, strict=True)), start)
            for taken in product(*open_options)
        )

    def _lane(self, choices: Mapping[Decision[Any], Any], start: World) -> "Lane":
        lane = Lane(program=self, choices=choices, joint=Distribution.pure(start))
        for item in self.items:
            item.run(lane)
        return lane


@dataclass
class Lane:
    program: Program
    choices: Mapping[Decision[Any], Any]
    joint: Distribution[World]
    edges: dict[Step[Any], Edge] = field(default_factory=dict)

    def read[T: Hashable](self, step: Step[Any], projection: Projection[T]) -> Distribution[T]:
        if projection not in self.program.readings[step]:
            raise GraphError(f"{projection.label} is not a reading of {step.name}")
        return self.edges[step].read(projection)

    def to_view(self) -> dict[str, Any]:
        paths = self.program.paths
        return {
            "program": self.program.name,
            "sides": {side.value: label for side, label in self.program.sides.items()},
            "nodes": [step.view(paths, self.edges[step]) for step in self.program.steps],
            "blocks": [block.view(paths) for block in self.program.blocks],
            "rules": [rule.view(paths) for rule in self.program.rules],
            "lanes": [
                {"decision": paths[decision], "outcome": str(outcome)}
                for decision, outcome in self.choices.items()
            ],
        }
