import operator
from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import product
from types import MappingProxyType
from typing import Any, ClassVar

from avelorn.core.distribution import Distribution
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


_NOTHING: Mapping[Any, Any] = MappingProxyType({})


def _shown(value: object) -> int | str:
    return value if isinstance(value, int) else str(value)


@dataclass(frozen=True, eq=False)
class Given[T]:
    name: str


@dataclass(frozen=True)
class World:
    outputs: tuple[tuple["Step[Any]", Any], ...] = ()

    def of[Out: Hashable](self, step: "Step[Out]") -> Out:
        for declared, value in self.outputs:
            if declared is step:
                return value
        raise GraphError(f"{step.name} has no output in this world")

    def then[Out: Hashable](self, step: "Step[Out]", value: Out) -> "World":
        return World((*self.outputs, (step, value)))


@dataclass(frozen=True)
class Situation:
    given: Mapping[Given[Any], Any]
    choices: Mapping["Decision[Any]", Any]


@dataclass
class Edge:
    joint: Distribution[World]
    count: Distribution[int] | None
    stacked: dict["Projection[Any]", Distribution[Any]] = field(default_factory=dict)

    def read[T: Hashable](self, projection: "Projection[T]") -> Distribution[T]:
        held = self.stacked.get(projection)
        if held is not None:
            return held
        classes = self.joint.map(projection.project)
        count = self.count
        if count is not None:
            nothing = Distribution.pure(type(next(iter(classes.mass)))())

            def copies(times: int) -> Distribution[T]:
                return times @ classes if times else nothing

            classes = count.bind(copies)
        self.stacked[projection] = classes
        return classes


@dataclass(frozen=True, eq=False)
class Projection[T: Hashable]:
    label: str
    project: Callable[[World], T]

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
    reads: tuple["Step[Any]", ...] = ()
    given: tuple[Given[Any], ...] = ()
    readings: list[Reading] = field(default_factory=list)

    @abstractmethod
    def outcomes(self, world: World, situation: Situation) -> Distribution[Out]: ...

    def output(self, label: str) -> Projection[Out]:
        def project(world: World) -> Out:
            return world.of(self)

        return Projection(label, project)

    def show(self, reading: Reading) -> None:
        self.readings.append(reading)

    def arguments(self, world: World, situation: Situation) -> tuple[Any, ...]:
        read = (world.of(step) for step in self.reads)
        supplied = (situation.given[declared] for declared in self.given)
        return (*read, *supplied)

    def declare(self, draft: "_Draft", prefix: str, visible: list["Step[Any]"]) -> None:
        path = f"{prefix}/{self.name}"
        for source in self.reads:
            if source not in visible:
                raise GraphError(f"{path} reads {source.name}, which is not in scope")
        draft.take(self, path)
        visible.append(self)

    def collect(self, draft: "_Draft") -> None:
        draft.steps.append(self)

    def run(self, run: "_Run") -> None:
        def advance(world: World) -> Distribution[World]:
            def attach(value: Out) -> World:
                return world.then(self, value)

            return self.outcomes(world, run.situation).map(attach)

        run.joint = run.joint.bind(advance)
        run.edges[self] = Edge(run.joint, run.count)

    def detail(self, edge: Edge) -> dict[str, Any]:
        return {}

    def view(self, paths: Mapping[Any, str], edge: Edge) -> dict[str, Any]:
        return {
            "path": paths[self],
            "step": self.name,
            "kind": self.kind,
            "side": self.side.value,
            "inputs": [paths[source] for source in self.reads],
            "edge": {"readings": [reading.view(edge) for reading in self.readings]},
            **self.detail(edge),
        }


@dataclass(frozen=True, eq=False, kw_only=True)
class Certain[Out: Hashable](Step[Out]):
    body: Callable[..., Out]

    def outcomes(self, world: World, situation: Situation) -> Distribution[Out]:
        return Distribution.pure(self.body(*self.arguments(world, situation)))


class Measurement[Out: Hashable](Certain[Out]):
    kind = "measurement"


class Consequence[Out: Hashable](Certain[Out]):
    kind = "consequence"


@dataclass(frozen=True, eq=False, kw_only=True)
class Roll[Out: Hashable](Step[Out]):
    kind = "roll"
    body: Callable[..., Distribution[Out]]
    target: Reading
    modifiers: tuple[Modifier, ...] = ()

    def outcomes(self, world: World, situation: Situation) -> Distribution[Out]:
        return self.body(*self.arguments(world, situation))

    def detail(self, edge: Edge) -> dict[str, Any]:
        return {
            "target": self.target.view(edge),
            "modifiers": [modifier.view() for modifier in self.modifiers],
        }


@dataclass(frozen=True, eq=False, kw_only=True)
class Decision[Out: Hashable](Step[Out]):
    kind = "decision"
    options: tuple[Out, ...]

    def outcomes(self, world: World, situation: Situation) -> Distribution[Out]:
        return Distribution.pure(situation.choices[self])

    def collect(self, draft: "_Draft") -> None:
        draft.steps.append(self)
        draft.decisions.append(self)

    def detail(self, edge: Edge) -> dict[str, Any]:
        return {"options": [str(option) for option in self.options]}


type Item = Step[Any] | Block


@dataclass(frozen=True, eq=False, kw_only=True)
class Block(ABC):
    kind: ClassVar[str]
    name: str
    items: tuple[Item, ...]

    def declare(self, draft: "_Draft", prefix: str, visible: list[Step[Any]]) -> None:
        path = f"{prefix}/{self.name}"
        self.check(path, visible)
        draft.take(self, path)
        inner = list(visible)
        for item in self.items:
            item.declare(draft, path, inner)

    def check(self, path: str, visible: list[Step[Any]]) -> None:
        return None

    def collect(self, draft: "_Draft") -> None:
        draft.blocks.append(self)

    def run(self, run: "_Run") -> None:
        outer, count = run.joint, run.count
        run.count = self.multiplier(run)
        for item in self.items:
            item.run(run)
        run.joint, run.count = outer, count

    def multiplier(self, run: "_Run") -> Distribution[int] | None:
        return run.count

    @abstractmethod
    def detail(self, paths: Mapping[Any, str]) -> dict[str, Any]: ...

    def view(self, paths: Mapping[Any, str]) -> dict[str, Any]:
        return {"path": paths[self], "kind": self.kind, **self.detail(paths)}


@dataclass(frozen=True, eq=False, kw_only=True)
class Group(Block):
    kind = "group"
    times: Step[int]
    collapsed: bool = False

    def check(self, path: str, visible: list[Step[Any]]) -> None:
        if self.times not in visible:
            raise GraphError(f"{path} runs {self.times.name} times, which is not in scope")

    def multiplier(self, run: "_Run") -> Distribution[int]:
        def counted(world: World) -> int:
            return world.of(self.times)

        mine = run.joint.map(counted)
        outer = run.count
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
class _Draft:
    paths: dict[Any, str] = field(default_factory=dict)
    taken: set[str] = field(default_factory=set)
    steps: list[Step[Any]] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    decisions: list[Decision[Any]] = field(default_factory=list)

    def take(self, item: Item, path: str) -> None:
        if path in self.taken:
            raise GraphError(f"{path} is declared twice")
        self.taken.add(path)
        self.paths[item] = path
        item.collect(self)


@dataclass
class _Run:
    situation: Situation
    joint: Distribution[World]
    count: Distribution[int] | None
    edges: dict[Step[Any], Edge] = field(default_factory=dict)


@dataclass
class Program:
    name: str
    sides: Mapping[Side, str]
    items: tuple[Item, ...]
    paths: Mapping[Any, str]
    steps: tuple[Step[Any], ...]
    blocks: tuple[Block, ...]
    decisions: tuple[Decision[Any], ...]
    rules: list[RuleNode] = field(default_factory=list)

    @classmethod
    def build(cls, name: str, sides: Mapping[Side, str], items: tuple[Item, ...]) -> "Program":
        draft = _Draft()
        visible: list[Step[Any]] = []
        for item in items:
            item.declare(draft, name, visible)
        return cls(
            name=name,
            sides=sides,
            items=items,
            paths=draft.paths,
            steps=tuple(draft.steps),
            blocks=tuple(draft.blocks),
            decisions=tuple(draft.decisions),
        )

    def attach(self, rule: RuleNode) -> None:
        for landing in rule.landings:
            if landing.at not in self.paths:
                raise GraphError(f"{rule.rule} lands on {landing.at.name}, which is not declared")
        self.rules.append(rule)

    def evaluate(
        self,
        given: Mapping[Given[Any], Any] = _NOTHING,
        choices: Mapping[Decision[Any], Any] = _NOTHING,
    ) -> "Evaluated":
        decisions = self.decisions
        open_options = [
            (decision.options if decision not in choices else (choices[decision],))
            for decision in decisions
        ]
        lanes = [
            self._lane(Situation(given, dict(zip(decisions, taken, strict=True))))
            for taken in product(*open_options)
        ]
        return Evaluated(lanes=tuple(lanes))

    def _lane(self, situation: Situation) -> "Lane":
        run = _Run(situation=situation, joint=Distribution.pure(World()), count=None)
        for item in self.items:
            item.run(run)
        return Lane(program=self, choices=situation.choices, edges=run.edges)


@dataclass
class Lane:
    program: Program
    choices: Mapping[Decision[Any], Any]
    edges: Mapping[Step[Any], Edge]

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


@dataclass
class Evaluated:
    lanes: tuple[Lane, ...]

    def only(self) -> Lane:
        if len(self.lanes) != 1:
            raise GraphError(f"{len(self.lanes)} lanes: fix a decision or read one lane")
        return self.lanes[0]

    def to_view(self) -> dict[str, Any]:
        return self.only().to_view()
