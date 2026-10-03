"""Programs loaded from YAML."""

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from avelorn.core.distribution import Distribution, Monoid
from avelorn.core.errors import AvelornError
from avelorn.core.graph import (
    GraphError,
    Item,
    Key,
    Lane,
    Program,
    Projection,
    Repeat,
    State,
    Step,
    Tally,
)
from avelorn.tow.data import DATA_DIR
from avelorn.tow.kernels import Standing
from avelorn.tow.schema.program import (
    FactInput,
    FactType,
    GroupEntry,
    KnownInput,
    ProgramFile,
    StateFact,
    StateFile,
    StepEntry,
)
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.steps import (
    HOLDERS,
    STEPS,
    Counted,
    Fact,
    Fielded,
    Offered,
    Output,
    Read,
    Spec,
    Summed,
)
from avelorn.tow.traits import Operand

STATE = DATA_DIR / "tow" / "state.yaml"
VOLLEY = DATA_DIR / "tow" / "programs" / "volley.yaml"

TYPES: Mapping[FactType, type] = MappingProxyType(
    {
        FactType.INT: int,
        FactType.BOOL: bool,
        FactType.STANDING: Standing,
        FactType.FIELDED: Fielded,
    }
)


_ZERO = Monoid(0)


class ProgramError(AvelornError):
    """A program refused at load or at evaluation."""


@dataclass(frozen=True)
class Input:
    """A value a program needs given."""

    state: State[Any]
    type: type


@dataclass(frozen=True)
class Loaded:
    """A loaded program."""

    program: Program
    inputs: Mapping[str, Input]

    def evaluate(self, knowns: Mapping[str, Hashable]) -> tuple["Evaluated", ...]:
        """Evaluate the program with every input given by name.

        Returns:
            One evaluation per lane.

        Raises:
            ProgramError: an input is missing, unknown or of the wrong type.
        """
        missing = sorted(set(self.inputs) - set(knowns))
        unknown = sorted(set(knowns) - set(self.inputs))
        if missing or unknown:
            raise ProgramError(
                f"{self.program.name} needs {missing or 'nothing more'} "
                f"and takes no {unknown or 'other input'}"
            )
        for name, value in knowns.items():
            expected = self.inputs[name].type
            if not isinstance(value, expected):
                raise ProgramError(f"{name} is a {expected.__name__}, not {value!r}")
        given = {self.inputs[name].state: value for name, value in knowns.items()}
        return tuple(
            Evaluated(self, lane, MappingProxyType(dict(knowns)))
            for lane in self.program.evaluate(state=given)
        )


@dataclass(frozen=True)
class Evaluated:
    """One lane of an evaluated program, read by path."""

    loaded: Loaded
    lane: Lane
    knowns: Mapping[str, Hashable]

    def at(self, path: str) -> "At":
        """The step instance at ``path``.

        Returns:
            A reader of that step in this lane.

        Raises:
            ProgramError: no step has that path, or it did not run in this lane.
        """
        program = self.loaded.program
        step = next((step for step in program.steps if program.paths[step] == path), None)
        if step is None:
            raise ProgramError(f"{program.name} has no step at {path}")
        if step not in self.lane.edges:
            raise ProgramError(f"{path} did not run in this lane")
        return At(self, step)


@dataclass(frozen=True)
class At:
    """A step instance in one lane."""

    evaluated: Evaluated
    step: Step[Any]

    def read(self, reading: str) -> Distribution[Any]:
        """The distribution a named reading of this step takes.

        Returns:
            The reading over this lane's worlds.

        Raises:
            ProgramError: the step shows no reading of that name.
        """
        lane = self.evaluated.lane
        shown = lane.program.readings[self.step]
        projection = next(
            (each for each in shown if isinstance(each, Projection) and each.label == reading),
            None,
        )
        if projection is None:
            raise ProgramError(f"{lane.program.paths[self.step]} shows no {reading}")
        return lane.read(self.step, projection)

    def part(self, part: str) -> "PartAt":
        """A part at this step.

        Returns:
            The part's reader.

        Raises:
            ProgramError: no fielded side has that part.
        """
        fielded = [
            value
            for value in self.evaluated.knowns.values()
            if isinstance(value, Fielded) and value.part == part
        ]
        if len(fielded) != 1:
            raise ProgramError(f"{part} is not the part of one fielded side")
        return PartAt(fielded[0])


@dataclass(frozen=True)
class PartAt:
    """A part at a step."""

    fielded: Fielded

    def characteristic(self, c: Characteristic) -> Operand[int | None]:
        """The characteristic in force.

        Returns:
            The operand; no rule is attached yet, so nothing changes it.
        """
        printed = self.fielded.characteristic(c)
        return Operand(Distribution.pure(printed), printed)


def _parsed[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate(yaml.safe_load(path.read_text()))
    except ValidationError as error:
        raise ProgramError(f"{path.name}: {error}") from error


@dataclass
class _Builder:
    source: str
    file: ProgramFile
    facts: Mapping[str, StateFact]
    inputs: dict[str, Input]
    states: dict[str, State[Any]] = field(default_factory=dict)
    written: set[str] = field(default_factory=set)

    def take(self, entry: FactInput | KnownInput, here: str) -> None:
        name = entry.name
        if name in self.inputs:
            raise self.error(here, f"{name} is an input twice")
        if isinstance(entry, FactInput):
            stated = self.facts.get(entry.fact)
            if stated is None:
                raise self.error(here, f"{entry.fact} is no fact {STATE.name} lists")
            kind = stated.type
        else:
            if entry.known in self.facts:
                raise self.error(here, f"{entry.known} is a state fact, not a known")
            kind = entry.type
        self.inputs[name] = Input(self.state(name), TYPES[kind])

    def block(
        self,
        entries: Sequence[GroupEntry | StepEntry | str],
        where: str,
        visible: dict[str, Step[Any]],
    ) -> tuple[Item, ...]:
        groups: dict[str, tuple[Repeat, dict[str, Step[Any]]]] = {}
        built: list[Item] = []
        for index, entry in enumerate(entries):
            here = f"{where}[{index}]"
            if isinstance(entry, GroupEntry):
                built.append(self.group(entry, here, visible, groups))
                continue
            named = StepEntry(step=entry) if isinstance(entry, str) else entry
            step = self.step(named, here, visible, groups)
            visible[step.name] = step
            built.append(step)
        return tuple(built)

    def group(
        self,
        entry: GroupEntry,
        here: str,
        visible: dict[str, Step[Any]],
        groups: dict[str, tuple[Repeat, dict[str, Step[Any]]]],
    ) -> Repeat:
        times = visible.get(entry.times)
        if times is None:
            raise self.error(
                here, f"{entry.group} runs {entry.times} times, which is not in scope"
            )
        inner = dict(visible)
        items = self.block(entry.items, f"{here}.items", inner)
        group = Repeat(name=entry.group, times=times, items=items)
        groups[entry.group] = (group, inner)
        return group

    def step(
        self,
        entry: StepEntry,
        here: str,
        visible: dict[str, Step[Any]],
        groups: Mapping[str, tuple[Repeat, dict[str, Step[Any]]]],
    ) -> Step[Any]:
        sequence = entry.sequence or self.file.sequence
        spec = STEPS.get((sequence, entry.step))
        if spec is None:
            raise self.error(here, f"{entry.step} is no step of the {sequence} sequence")
        tally = self.tally(spec, entry, here, groups)
        inputs = tuple(self.key(read, spec, here, visible, tally) for read in spec.reads)
        target = None
        if spec.target is not None:
            target = self.projection("needed", spec.target, spec, here, visible, tally)
        writes = None if spec.writes is None else self.write(spec.writes, here)
        step = spec.build(inputs, target, writes)
        own = {**visible, spec.name: step}
        for name in entry.readings:
            offered = spec.readings.get(name)
            if offered is None:
                raise self.error(here, f"{spec.name} offers no reading {name}")
            step.show(self.projection(name, offered, spec, here, own, tally))
        return step

    def tally(
        self,
        spec: Spec,
        entry: StepEntry,
        here: str,
        groups: Mapping[str, tuple[Repeat, dict[str, Step[Any]]]],
    ) -> Tally[int] | None:
        if spec.counts is None:
            if entry.tallies:
                raise self.error(here, f"{spec.name} sums no group")
            return None
        if not entry.tallies:
            raise self.error(here, f"{spec.name} needs the groups it tallies")
        counts: dict[Repeat, Projection[int]] = {}
        for name in entry.tallies:
            if name not in groups:
                raise self.error(here, f"{spec.name} tallies {name}, no group before it here")
            group, inner = groups[name]
            counts[group] = self.counted(spec.counts, spec, here, inner)
        return Tally(spec.counts.label, counts)

    def counted(
        self, counts: Counted, spec: Spec, here: str, inner: Mapping[str, Step[Any]]
    ) -> Projection[int]:
        reads = tuple(self.output(read, spec, here, inner) for read in counts.reads)
        return Projection(counts.label, reads, counts.project, _ZERO)

    def projection(
        self,
        label: str,
        offered: Offered,
        spec: Spec,
        here: str,
        visible: Mapping[str, Step[Any]],
        tally: Tally[int] | None,
    ) -> Projection[Any]:
        reads = tuple(self.key(read, spec, here, visible, tally) for read in offered.reads)
        return Projection(label, reads, offered.project, offered.aggregation)

    def key(
        self,
        read: Read,
        spec: Spec,
        here: str,
        visible: Mapping[str, Step[Any]],
        tally: Tally[int] | None,
    ) -> Key:
        match read:
            case Fact():
                return self.read(read, spec, here)
            case Output():
                return self.output(read, spec, here, visible)
            case Summed():
                if tally is None:
                    raise self.error(here, f"{spec.name} reads a tally it was not given")
                return tally

    def output(self, read: Output, spec: Spec, here: str, visible: Mapping[str, Step[Any]]) -> Key:
        step = visible.get(read.step)
        if step is None:
            raise self.error(here, f"{spec.name} reads {read.step}, which is not in scope")
        return step.key

    def read(self, fact: Fact, spec: Spec, here: str) -> State[Any]:
        name = fact.full
        if name in self.inputs:
            return self.inputs[name].state
        if name in self.written:
            return self.states[name]
        raise self.error(here, f"{spec.name} reads {name}, which is no input and is not written")

    def write(self, fact: Fact, here: str) -> State[Any]:
        name = fact.full
        stated = self.facts.get(fact.name)
        if stated is None or fact.of is None:
            raise self.error(here, f"writes {name}, which {STATE.name} does not list")
        self.written.add(name)
        return self.state(name)

    def state(self, name: str) -> State[Any]:
        if name not in self.states:
            self.states[name] = State(name)
        return self.states[name]

    def error(self, here: str, message: str) -> ProgramError:
        return ProgramError(f"{self.source}: {here}: {message}")


def load_program(path: Path, state: Path = STATE) -> Loaded:
    """Load and check a program file.

    Returns:
        The built program and the inputs it needs.

    Raises:
        ProgramError: an entry does not load; the message names its path in the file.
    """
    file = _parsed(path, ProgramFile)
    facts = {fact.fact: fact for fact in _parsed(state, StateFile).facts}
    builder = _Builder(path.name, file, facts, {})
    for index, entry in enumerate(file.inputs):
        builder.take(entry, f"inputs[{index}]")
    items = builder.block(file.items, "items", {})
    sides = {holder: str(side) for side, holder in HOLDERS.items()}
    try:
        program = Program.build(file.program, sides, items)
    except GraphError as error:
        raise ProgramError(f"{path.name}: {error}") from error
    for given in builder.inputs.values():
        program.hold(given.state)
    return Loaded(program, MappingProxyType(builder.inputs))
