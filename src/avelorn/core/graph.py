import operator
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


# A step's own output is a local, keyed by the step.
type Key = Step[Any] | State[Any]


@dataclass(frozen=True)
class World:
    """One way things could have gone: the values of the state and of the locals."""

    values: frozenset[tuple[Key, Any]] = frozenset()

    def of[T: Hashable](self, key: "Step[T] | State[T]") -> T:
        for held, value in self.values:
            if held is key:
                return value
        raise GraphError(f"{key.name} is not held in this world")

    def holding(self, key: Key, value: Hashable) -> "World":
        kept = {pair for pair in self.values if pair[0] is not key}
        return World(frozenset({*kept, (key, value)}))

    def keeping(self, keys: frozenset[Key]) -> "World":
        return World(frozenset(pair for pair in self.values if pair[0] in keys))


@dataclass
class Edge:
    joint: Distribution[World]
    count: Distribution[int] | None
    stacked: dict["Projection[Any]", Distribution[Any]] = field(default_factory=dict)

    def read[T: Hashable](self, projection: "Projection[T]") -> Distribution[T]:
        held = self.stacked.get(projection)
        if held is not None:
            return held
        classes = self.joint.map(projection.of)
        count = self.count
        if count is not None:

            def copies(times: int) -> Distribution[T]:
                return classes.repeat(times, projection.aggregation)

            classes = count.bind(copies)
        self.stacked[projection] = classes
        return classes


@dataclass(frozen=True, eq=False)
class Projection[T: Hashable]:
    label: str
    reads: tuple[Key, ...]
    # Takes the values of `reads`, positionally.
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
    # Inputs are earlier in-scope locals and state facts, passed positionally to the kernel.
    inputs: tuple[Key, ...] = ()
    kernel: Kernel[Out] | None = None
    readings: list[Reading] = field(default_factory=list)
    # A step that writes a state fact replaces it and declares no local.
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

    def declare(self, program: "Program", prefix: str, visible: list["Step[Any]"]) -> None:
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

    def collect(self, program: "Program") -> None:
        program.steps.append(self)
        program.readings[self] = self.shown()

    # Returns what must be held before the step runs.
    def liveness(
        self, after: frozenset[Key], live: dict["Item", frozenset[Key]]
    ) -> frozenset[Key]:
        live[self] = after
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
        lane.edges[self] = Edge(edge, lane.count)
        lane.joint = edge if held <= after else edge.map(onward)

    def detail(self, edge: Edge) -> dict[str, Any]:
        return {}

    def view(self, paths: Mapping[Any, str], edge: Edge) -> dict[str, Any]:
        return {
            "path": paths[self],
            "step": self.name,
            "kind": self.kind,
            "side": self.side.value,
            "inputs": [paths[source] for source in self.inputs],
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
    # A scoped block's locals die at its exit; its state writes survive it.
    scoped: ClassVar[bool] = True
    name: str
    items: tuple[Item, ...]

    def declare(self, program: "Program", prefix: str, visible: list[Step[Any]]) -> None:
        path = f"{prefix}/{self.name}"
        self.check(path, visible)
        program.take(self, path)
        inner = list(visible) if self.scoped else visible
        for item in self.items:
            item.declare(program, path, inner)

    def check(self, path: str, visible: list[Step[Any]]) -> None:
        return None

    def collect(self, program: "Program") -> None:
        program.blocks.append(self)

    def liveness(
        self, after: frozenset[Key], live: dict["Item", frozenset[Key]]
    ) -> frozenset[Key]:
        for item in reversed(self.items):
            after = item.liveness(after, live)
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
    """Runs its items for one attack; the outer worlds resume unchanged at its exit."""

    kind = "repeat"
    times: Step[int]
    collapsed: bool = False

    def declare(self, program: "Program", prefix: str, visible: list[Step[Any]]) -> None:
        first = len(program.steps)
        super().declare(program, prefix, visible)
        for step in program.steps[first:]:
            if step.writes is not None:
                raise GraphError(
                    f"{program.paths[step]} writes {step.writes.name} inside a group, "
                    "which cannot carry state out"
                )

    def check(self, path: str, visible: list[Step[Any]]) -> None:
        if self.times not in visible:
            raise GraphError(f"{path} runs {self.times.name} times, which is not in scope")

    def liveness(
        self, after: frozenset[Key], live: dict["Item", frozenset[Key]]
    ) -> frozenset[Key]:
        live[self] = after
        inside = super().liveness(frozenset(), live)
        return after | inside | {self.times}

    def run(self, lane: "Lane") -> None:
        outer, count = lane.joint, lane.count
        lane.count = self.multiplier(lane)
        super().run(lane)
        kept = lane.program.live[self]

        def resumed(world: World) -> World:
            return world.keeping(kept)

        lane.joint, lane.count = outer.map(resumed), count

    def multiplier(self, lane: "Lane") -> Distribution[int]:
        def counted(world: World) -> int:
            return world.of(self.times)

        mine = lane.joint.map(counted)
        outer = lane.count
        return mine if outer is None else outer.combine(mine, operator.mul)

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

    def check(self, path: str, visible: list[Step[Any]]) -> None:
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
    # What each step's edge, and each group's exit, keeps of a world.
    live: dict[Item, frozenset[Key]] = field(default_factory=dict)
    entry: frozenset[Key] = frozenset()

    @classmethod
    def build(cls, name: str, sides: Mapping[Side, str], items: tuple[Item, ...]) -> "Program":
        program = cls(name=name, sides=sides, items=items)
        visible: list[Step[Any]] = []
        for item in items:
            item.declare(program, name, visible)
        needed: frozenset[Key] = frozenset()
        for item in reversed(items):
            needed = item.liveness(needed, program.live)
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
    count: Distribution[int] | None = None
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
