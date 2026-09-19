import operator
from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from inspect import signature
from itertools import product
from types import MappingProxyType
from typing import Any, ClassVar

from avelorn.core.distribution import Distribution, Kernel
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


@dataclass(frozen=True)
class Trace:
    """Partial execution trace so far."""

    outputs: tuple[tuple["Step[Any]", Any], ...] = ()

    def of[Out: Hashable](self, step: "Step[Out]") -> Out:
        for declared, value in self.outputs:
            if declared is step:
                return value
        raise GraphError(f"{step.name} has not run in this trace")

    def then[Out: Hashable](self, step: "Step[Out]", value: Out) -> "Trace":
        return Trace((*self.outputs, (step, value)))


@dataclass
class Edge:
    joint: Distribution[Trace]
    count: Distribution[int] | None
    stacked: dict["Projection[Any]", Distribution[Any]] = field(default_factory=dict)

    def read[T: Hashable](self, projection: "Projection[T]") -> Distribution[T]:
        held = self.stacked.get(projection)
        if held is not None:
            return held
        classes = self.joint.map(projection.project)
        count = self.count
        if count is not None:

            def copies(times: int) -> Distribution[T]:
                return classes.repeat(times, projection.identity)

            classes = count.bind(copies)
        self.stacked[projection] = classes
        return classes


@dataclass(frozen=True, eq=False)
class Projection[T: Hashable]:
    label: str
    project: Callable[[Trace], T]
    identity: T

    def view(self, edge: Edge) -> dict[str, Any]:
        read = edge.read(self)
        outcomes = [{"value": _shown(value), "p": float(p)} for value, p in read.mass.items()]
        return {"label": self.label, "outcomes": outcomes}


@dataclass(frozen=True, eq=False)
class Scalar[T]:
    label: str
    value: T

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
    # Inputs are outputs of earlier in-scope steps, passed positionally to the kernel.
    inputs: tuple["Step[Any]", ...] = ()
    kernel: Kernel[Out] | None = None
    readings: list[Reading] = field(default_factory=list)

    @abstractmethod
    def outcomes(self, world: Trace, lane: "Lane") -> Distribution[Out]: ...

    def output(self, label: str, identity: Out) -> Projection[Out]:
        def project(world: Trace) -> Out:
            return world.of(self)

        return Projection(label, project, identity)

    def show(self, reading: Reading) -> None:
        self.readings.append(reading)

    def arguments(self, world: Trace) -> tuple[Any, ...]:
        return tuple(world.of(step) for step in self.inputs)

    def declare(self, program: "Program", prefix: str, visible: list["Step[Any]"]) -> None:
        path = f"{prefix}/{self.name}"
        for source in self.inputs:
            if source not in visible:
                raise GraphError(f"{path} inputs {source.name}, which is not in scope")
        if self.kernel is not None:
            try:
                signature(self.kernel).bind(*(None for _ in self.inputs))
            except (TypeError, ValueError) as error:
                raise GraphError(
                    f"{path} kernel cannot accept {len(self.inputs)} positional inputs"
                ) from error
        program.take(self, path)
        visible.append(self)

    def collect(self, program: "Program") -> None:
        program.steps.append(self)

    def run(self, lane: "Lane") -> None:
        def advance(world: Trace) -> Distribution[Trace]:
            def attach(value: Out) -> Trace:
                return world.then(self, value)

            return self.outcomes(world, lane).map(attach)

        lane.joint = lane.joint.bind(advance)
        lane.edges[self] = Edge(lane.joint, lane.count)

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

    def outcomes(self, world: Trace, lane: "Lane") -> Distribution[Out]:
        return self.kernel(*self.arguments(world))


@dataclass(frozen=True, eq=False, kw_only=True)
class Consequence[Out: Hashable](Step[Out]):
    kind = "consequence"
    kernel: Kernel[Out]

    def outcomes(self, world: Trace, lane: "Lane") -> Distribution[Out]:
        return self.kernel(*self.arguments(world))


@dataclass(frozen=True, eq=False, kw_only=True)
class Roll[Out: Hashable](Step[Out]):
    kind = "roll"
    kernel: Kernel[Out]
    target: Reading
    modifiers: tuple[Modifier, ...] = ()

    def outcomes(self, world: Trace, lane: "Lane") -> Distribution[Out]:
        return self.kernel(*self.arguments(world))

    def detail(self, edge: Edge) -> dict[str, Any]:
        return {
            "target": self.target.view(edge),
            "modifiers": [modifier.view() for modifier in self.modifiers],
        }


@dataclass(frozen=True, eq=False, kw_only=True)
class Decision[Out: Hashable](Step[Out]):
    kind = "decision"
    options: tuple[Out, ...]

    def outcomes(self, world: Trace, lane: "Lane") -> Distribution[Out]:
        return Distribution.pure(lane.choices[self])

    def collect(self, program: "Program") -> None:
        program.steps.append(self)
        program.decisions.append(self)

    def detail(self, edge: Edge) -> dict[str, Any]:
        return {"options": [str(option) for option in self.options]}


type Item = Step[Any] | Block


@dataclass(frozen=True, eq=False, kw_only=True)
class Block(ABC):
    kind: ClassVar[str]
    name: str
    items: tuple[Item, ...]

    def declare(self, program: "Program", prefix: str, visible: list[Step[Any]]) -> None:
        path = f"{prefix}/{self.name}"
        self.check(path, visible)
        program.take(self, path)
        inner = list(visible)
        for item in self.items:
            item.declare(program, path, inner)

    def check(self, path: str, visible: list[Step[Any]]) -> None:
        return None

    def collect(self, program: "Program") -> None:
        program.blocks.append(self)

    def run(self, lane: "Lane") -> None:
        outer, count = lane.joint, lane.count
        lane.count = self.multiplier(lane)
        for item in self.items:
            item.run(lane)
        lane.joint, lane.count = outer, count

    def multiplier(self, lane: "Lane") -> Distribution[int] | None:
        return lane.count

    @abstractmethod
    def detail(self, paths: Mapping[Any, str]) -> dict[str, Any]: ...

    def view(self, paths: Mapping[Any, str]) -> dict[str, Any]:
        return {"path": paths[self], "kind": self.kind, **self.detail(paths)}


@dataclass(frozen=True, eq=False, kw_only=True)
class Group(Block, ABC):
    kind = "group"

    @abstractmethod
    def run(self, lane: "Lane") -> None: ...


@dataclass(frozen=True, eq=False, kw_only=True)
class Repeat(Group):
    kind = "repeat"
    times: Step[int]
    collapsed: bool = False

    def check(self, path: str, visible: list[Step[Any]]) -> None:
        if self.times not in visible:
            raise GraphError(f"{path} runs {self.times.name} times, which is not in scope")

    def run(self, lane: "Lane") -> None:
        outer, count = lane.joint, lane.count
        lane.count = self.multiplier(lane)
        for item in self.items:
            item.run(lane)
        lane.joint, lane.count = outer, count

    def multiplier(self, lane: "Lane") -> Distribution[int]:
        def counted(world: Trace) -> int:
            return world.of(self.times)

        mine = lane.joint.map(counted)
        outer = lane.count
        return mine if outer is None else outer.combine(mine, operator.mul)

    def detail(self, paths: Mapping[Any, str]) -> dict[str, Any]:
        return {"times": paths[self.times], "collapsed": self.collapsed}


@dataclass(frozen=True, eq=False, kw_only=True)
class Slot(Block):
    kind = "slot"

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

    @classmethod
    def build(cls, name: str, sides: Mapping[Side, str], items: tuple[Item, ...]) -> "Program":
        program = cls(name=name, sides=sides, items=items)
        visible: list[Step[Any]] = []
        for item in items:
            item.declare(program, name, visible)
        return program

    def take(self, item: Item, path: str) -> None:
        if path in self.paths.values():
            raise GraphError(f"{path} is declared twice")
        self.paths[item] = path
        item.collect(self)

    def attach(self, rule: RuleNode) -> None:
        for landing in rule.landings:
            if landing.at not in self.paths:
                raise GraphError(f"{rule.rule} lands on {landing.at.name}, which is not declared")
        self.rules.append(rule)

    def evaluate(
        self, choices: Mapping[Decision[Any], Any] = MappingProxyType({})
    ) -> tuple["Lane", ...]:
        open_options = [
            (choices[decision],) if decision in choices else decision.options
            for decision in self.decisions
        ]
        return tuple(
            self._lane(dict(zip(self.decisions, taken, strict=True)))
            for taken in product(*open_options)
        )

    def _lane(self, choices: Mapping[Decision[Any], Any]) -> "Lane":
        lane = Lane(program=self, choices=choices, joint=Distribution.pure(Trace()))
        for item in self.items:
            item.run(lane)
        return lane


@dataclass
class Lane:
    program: Program
    choices: Mapping[Decision[Any], Any]
    joint: Distribution[Trace]
    count: Distribution[int] | None = None
    edges: dict[Step[Any], Edge] = field(default_factory=dict)

    def read[T: Hashable](self, step: Step[Any], projection: Projection[T]) -> Distribution[T]:
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
