"""Programs loaded from YAML."""

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
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
    Mark,
    Program,
    Projection,
    Repeat,
    State,
    Step,
    Tally,
)
from avelorn.tow.attach import Attachment, attach_rules
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
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.steps import (
    CHANGED,
    STEPS,
    Changed,
    Counted,
    Fact,
    Fielded,
    Holding,
    Offered,
    Output,
    Read,
    Spec,
    Summed,
    holdings,
)
from avelorn.tow.traits import Operand

STATE = DATA_DIR / "tow" / "state.yaml"
VOLLEY = DATA_DIR / "tow" / "programs" / "volley.yaml"

TYPES: Mapping[FactType, type] = MappingProxyType(
    {
        FactType.INT: int,
        FactType.BOOL: bool,
        FactType.STANDING: Standing,
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
    """A loaded program file, with the corpus rules it attaches from.

    ``specs`` are the printed steps the program makes, in file order.
    """

    source: str
    file: ProgramFile
    facts: Mapping[str, StateFact]
    inputs: Mapping[str, Input]
    specs: tuple[Spec, ...]
    rules: Mapping[str, Rule]

    @property
    def sides(self) -> tuple[Side, ...]:
        """The sides each build fields."""
        return tuple(self.file.fielded)

    @property
    def states(self) -> Mapping[str, State[Any]]:
        """The state each input is held under, by the input's name."""
        return MappingProxyType({name: given.state for name, given in self.inputs.items()})

    def built(self, fielded: Mapping[Side, Fielded]) -> "Built":
        """Build the program for one fielding of each side, and attach their rules.

        Each build makes its own steps and rule nodes, so no two fieldings share them.

        Returns:
            The built program.

        Raises:
            ProgramError: a side the program fields is not given, or a side it does not
                field is.
        """
        missing = [str(side) for side in self.sides if side not in fielded]
        if missing:
            raise ProgramError(f"{self.file.program} needs the {', '.join(missing)} fielded")
        stray = [str(side) for side in fielded if side not in self.sides]
        if stray:
            raise ProgramError(f"{self.file.program} fields no {', '.join(stray)}")
        states = dict(self.states)
        builder = _Builder(self.source, self.file, self.facts, dict(self.inputs), fielded, states)
        program = builder.build()
        attachment = attach_rules(program, builder.specs, fielded, self.rules, self.states)
        program.attach(attachment.nodes)
        return Built(
            self.inputs,
            program,
            MappingProxyType(builder.specs),
            MappingProxyType(dict(fielded)),
            attachment,
        )


@dataclass(frozen=True)
class Built:
    """A program built for one fielding of each side, their rules attached."""

    inputs: Mapping[str, Input]
    program: Program
    specs: Mapping[Step[Any], Spec]
    fielded: Mapping[Side, Fielded]
    attachment: Attachment

    def evaluate(self, knowns: Mapping[str, Hashable]) -> tuple["Evaluated", ...]:
        """Evaluate the program with every input given by name.

        Returns:
            One evaluation per lane.

        Raises:
            ProgramError: an input is missing, unknown or of the wrong type.
        """
        missing = sorted(set(self.inputs) - set(knowns))
        if missing:
            raise ProgramError(f"{self.program.name} needs {', '.join(missing)}")
        unknown = sorted(set(knowns) - set(self.inputs))
        if unknown:
            raise ProgramError(f"{self.program.name} takes no input {', '.join(unknown)}")
        for name, value in knowns.items():
            expected = self.inputs[name].type
            if type(value) is not expected:
                raise ProgramError(f"{name} expects {expected.__name__}; got {value!r}")
        given = {self.inputs[name].state: value for name, value in knowns.items()}
        return tuple(
            Evaluated(self, lane, MappingProxyType(dict(knowns)))
            for lane in self.program.evaluate(state=given)
        )


@dataclass(frozen=True)
class Evaluated:
    """One lane of an evaluated program, read by path."""

    built: Built
    lane: Lane
    knowns: Mapping[str, Hashable]

    def at(self, path: str) -> "At":
        """The step instance at ``path``.

        Returns:
            A reader of that step in this lane.

        Raises:
            ProgramError: no step has that path, or it did not run in this lane.
        """
        program = self.lane.program
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

    def part(self, side: Side, part: str) -> "PartAt":
        """A part of one side at this step.

        Returns:
            The part's reader.

        Raises:
            ProgramError: that side fields no such part.
        """
        fielded = self.evaluated.built.fielded[side]
        if fielded.part != part:
            raise ProgramError(f"the {side} fields no part {part}")
        return PartAt(self, side, fielded)


@dataclass(frozen=True)
class PartAt:
    """A part at a step."""

    at: At
    side: Side
    fielded: Fielded

    def characteristic(self, c: Characteristic) -> Operand[int | None]:
        """The characteristic in force at the step.

        Returns:
            The operand; no attached rule changes it yet.
        """
        printed = self.fielded.characteristic(c)
        spec = self.at.evaluated.built.specs[self.at.step]
        resolve = spec.in_force.get((self.side, c))
        value = printed if resolve is None else resolve(self.fielded)
        return Operand(Distribution.pure(value), printed)


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
    fielded: Mapping[Side, Fielded] | None
    states: dict[str, State[Any]] = field(default_factory=dict)
    specs: dict[Step[Any], Spec] = field(default_factory=dict)
    written: set[str] = field(default_factory=set)

    def build(self) -> Program:
        items = self.block(self.file.items, "items", {})
        try:
            program = Program.build(self.file.program, tuple(map(str, self.file.fielded)), items)
        except GraphError as error:
            raise ProgramError(f"{self.source}: {error}") from error
        for given in self.inputs.values():
            program.hold(given.state)
        return program

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
                raise self.error(here, f"{entry.known} is listed in {STATE.name}")
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
        group = Repeat(name=entry.group, times=times.output("times", _ZERO), items=items)
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
        changed = Mark[tuple[Hashable, ...]](spec.name) if CHANGED in spec.reads else None
        bound = self.held(spec.reads, spec, here)
        kernel = partial(spec.kernel, *bound) if bound else spec.kernel
        inputs = tuple(
            self.key(read, spec, here, visible, tally, changed)
            for read in spec.reads[len(bound) :]
        )
        target = printed = None
        if spec.target is not None:
            target = self.projection("needed", spec.target, spec, here, visible, tally, changed)
        if spec.printed is not None:
            printed = self.projection("printed", spec.printed, spec, here, visible, tally, changed)
        writes = None if spec.writes is None else self.write(spec.writes, here)
        step = spec.build(kernel, inputs, target, writes, changed, printed)
        self.specs[step] = spec
        own = {**visible, spec.name: step}
        for name in entry.readings:
            offered = spec.readings.get(name)
            if offered is None:
                raise self.error(here, f"{spec.name} offers no reading {name}")
            step.show(self.projection(name, offered, spec, here, own, tally, changed))
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
        changed: Mark[tuple[Hashable, ...]] | None,
    ) -> Projection[Any]:
        bound = self.held(offered.reads, spec, here)
        project = partial(offered.project, *bound) if bound else offered.project
        reads = tuple(
            self.key(read, spec, here, visible, tally, changed)
            for read in offered.reads[len(bound) :]
        )
        return Projection(label, reads, project, offered.aggregation)

    def held(self, reads: tuple[Read, ...], spec: Spec, here: str) -> tuple[Fielded | None, ...]:
        bound: list[Fielded | None] = []
        for holding in holdings(reads):
            if holding.of not in self.file.fielded:
                raise self.error(
                    here, f"{spec.name} reads the {holding.of}, which {self.source} does not field"
                )
            bound.append(None if self.fielded is None else self.fielded[holding.of])
        return tuple(bound)

    def key(
        self,
        read: Read,
        spec: Spec,
        here: str,
        visible: Mapping[str, Step[Any]],
        tally: Tally[int] | None,
        changed: Mark[tuple[Hashable, ...]] | None,
    ) -> Key:
        match read:
            case Holding():
                raise self.error(here, f"{spec.name} reads the {read.of} after another input")
            case Fact():
                return self.read(read, spec, here)
            case Output():
                return self.output(read, spec, here, visible)
            case Summed():
                if tally is None:
                    raise self.error(here, f"{spec.name} reads a tally it was not given")
                return tally
            case Changed():
                if changed is None:
                    raise self.error(here, f"{spec.name} reads changes it does not mark")
                return changed

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


def load_program(path: Path, rules: Mapping[str, Rule], state: Path = STATE) -> Loaded:
    """Load and check a program file.

    The check builds the program once with no side fielded, so an entry that
    does not load fails here with a :class:`ProgramError` naming its path in
    the file.

    Returns:
        The loaded program, the inputs it needs and the rules it attaches from.
    """
    file = _parsed(path, ProgramFile)
    facts = {fact.fact: fact for fact in _parsed(state, StateFile).facts}
    builder = _Builder(path.name, file, facts, {}, None)
    for index, entry in enumerate(file.inputs):
        builder.take(entry, f"inputs[{index}]")
    builder.build()
    inputs = MappingProxyType(builder.inputs)
    return Loaded(path.name, file, facts, inputs, tuple(builder.specs.values()), rules)
