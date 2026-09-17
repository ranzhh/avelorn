from abc import ABC, abstractmethod
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from avelorn.core.distribution import Distribution
from avelorn.core.errors import AvelornError


class GraphError(AvelornError): ...


class StepKind(StrEnum):
    MEASUREMENT = "measurement"
    DECISION = "decision"
    ROLL = "roll"
    CONSEQUENCE = "consequence"


class BlockKind(StrEnum):
    GROUP = "group"
    SLOT = "slot"
    LANES = "lanes"


class Side(StrEnum):
    THIS_MODEL = "this-model"
    THE_ENEMY = "the-enemy"


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


@dataclass(frozen=True, eq=False)
class Projection[T: Hashable]:
    label: str
    project: Callable[[World], T]


@dataclass(frozen=True, eq=False)
class Scalar[T]:
    label: str
    value: T


type Reading = Projection[Any] | Scalar[Any]


@dataclass(frozen=True)
class Modifier:
    rule: str
    move: int


@dataclass(frozen=True, eq=False, kw_only=True)
class Step[Out: Hashable](ABC):
    kind: ClassVar[StepKind]
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


@dataclass(frozen=True, eq=False, kw_only=True)
class Certain[Out: Hashable](Step[Out]):
    body: Callable[..., Out]

    def outcomes(self, world: World, situation: Situation) -> Distribution[Out]:
        return Distribution.pure(self.body(*self.arguments(world, situation)))


class Measurement[Out: Hashable](Certain[Out]):
    kind = StepKind.MEASUREMENT


class Consequence[Out: Hashable](Certain[Out]):
    kind = StepKind.CONSEQUENCE


@dataclass(frozen=True, eq=False, kw_only=True)
class Roll[Out: Hashable](Step[Out]):
    kind = StepKind.ROLL
    body: Callable[..., Distribution[Out]]
    target: Reading
    modifiers: tuple[Modifier, ...] = ()

    def outcomes(self, world: World, situation: Situation) -> Distribution[Out]:
        return self.body(*self.arguments(world, situation))


@dataclass(frozen=True, eq=False, kw_only=True)
class Decision[Out: Hashable](Step[Out]):
    kind = StepKind.DECISION
    options: tuple[Out, ...]

    def outcomes(self, world: World, situation: Situation) -> Distribution[Out]:
        return Distribution.pure(situation.choices[self])

    def collect(self, draft: "_Draft") -> None:
        draft.steps.append(self)
        draft.decisions.append(self)


type Item = Step[Any] | Block


@dataclass(frozen=True, eq=False, kw_only=True)
class Block(ABC):
    kind: ClassVar[BlockKind]
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


@dataclass(frozen=True, eq=False, kw_only=True)
class Group(Block):
    kind = BlockKind.GROUP
    times: Step[int]
    collapsed: bool = False

    def check(self, path: str, visible: list[Step[Any]]) -> None:
        if self.times not in visible:
            raise GraphError(f"{path} runs {self.times.name} times, which is not in scope")


@dataclass(frozen=True, eq=False, kw_only=True)
class Slot(Block):
    kind = BlockKind.SLOT


@dataclass(frozen=True, eq=False, kw_only=True)
class Lanes(Block):
    kind = BlockKind.LANES
    decision: Decision[Any]

    def check(self, path: str, visible: list[Step[Any]]) -> None:
        if self.decision not in visible:
            raise GraphError(f"{path} splits on {self.decision.name}, which is not in scope")


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
class Program:
    name: str
    sides: Mapping[Side, str]
    items: tuple[Item, ...]
    paths: Mapping[Any, str]
    steps: tuple[Step[Any], ...]
    blocks: tuple[Block, ...]
    decisions: tuple[Decision[Any], ...]

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
