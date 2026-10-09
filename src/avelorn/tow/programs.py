"""Programs loaded from YAML."""

from collections.abc import Hashable, Iterable, Mapping
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
    By,
    Decision,
    GraphError,
    Item,
    Key,
    Lane,
    Mark,
    Program,
    Projection,
    Repeat,
    Sequence,
    Slot,
    State,
    Step,
    Tally,
)
from avelorn.tow.attach import Attachment, attach_rules
from avelorn.tow.changes import Uses
from avelorn.tow.contingent import ChargeArc
from avelorn.tow.data import DATA_DIR
from avelorn.tow.fielding import Fielding, Part
from avelorn.tow.kernels import Standings
from avelorn.tow.schema.program import (
    FactInput,
    FactType,
    GroupEntry,
    KnownInput,
    ProgramFile,
    SlotEntry,
    SlotsEntry,
    StateFact,
    StateFile,
    StepEntry,
)
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.steps import (
    AUTOMATIC_HITS,
    CHANGED,
    SLOTTED,
    STEPS,
    Changed,
    Choice,
    Counted,
    Fact,
    Holding,
    Offered,
    Output,
    Read,
    Spec,
    Striking,
    Summed,
    bound,
    share,
    weapon_choices,
)
from avelorn.tow.traits import Operand

STATE = DATA_DIR / "tow" / "state.yaml"
VOLLEY = DATA_DIR / "tow" / "programs" / "volley.yaml"
ROUND = DATA_DIR / "tow" / "programs" / "round.yaml"

TYPES: Mapping[FactType, type] = MappingProxyType(
    {
        FactType.INT: int,
        FactType.BOOL: bool,
        FactType.STANDING: Standings,
        FactType.USES: Uses,
        FactType.ARC: ChargeArc,
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
    specs: tuple[Spec | Choice, ...]
    rules: Mapping[str, Rule]

    @property
    def sides(self) -> tuple[Side, ...]:
        """The sides each build fields."""
        return tuple(self.file.fielded)

    @property
    def states(self) -> Mapping[str, State[Any]]:
        """The state each input is held under, by the input's name."""
        return MappingProxyType({name: given.state for name, given in self.inputs.items()})

    def built(self, fielded: Mapping[Side, Fielding]) -> "Built":
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
        attachment = attach_rules(
            program, builder.specs, fielded, self.rules, self.states, builder.wielding
        )
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
    specs: Mapping[Step[Any], Spec | Choice]
    fielded: Mapping[Side, Fielding]
    attachment: Attachment

    def evaluate(
        self,
        knowns: Mapping[str, Hashable],
        choices: Mapping[Side, Hashable] = MappingProxyType({}),
    ) -> tuple["Evaluated", ...]:
        """Evaluate the program with every input given by name.

        ``choices`` gives the option a side takes at its weapon choice, which
        then opens no lane. Each other option a side may take is a lane of its
        own.

        Returns:
            One evaluation per lane.

        Raises:
            ProgramError: an input is missing, unknown or of the wrong type, or
                an option given is not taken in every world, as a rule forbids it.
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
        pinned = self.pinned(choices)
        lanes = self.program.evaluate(pinned, given)
        for lane in lanes:
            for decision, option in pinned.items():
                taken = lane.read(decision, decision.taken)
                if any(each.by is not By.CHOSEN for each in taken.mass):
                    path = self.program.paths[decision]
                    raise ProgramError(f"{option} is not allowed at {path}")
        return tuple(Evaluated(self, lane, MappingProxyType(dict(knowns))) for lane in lanes)

    def pinned(self, choices: Mapping[Side, Hashable]) -> dict[Decision[Any], Hashable]:
        """Each option given, at the weapon choice of its side.

        Returns:
            The option, by decision.

        Raises:
            ProgramError: a side makes no weapon choice, or is given an option it lacks.
        """
        made = weapon_choices(self.specs)
        pinned: dict[Decision[Any], Hashable] = {}
        for side, option in choices.items():
            decision = made.get(side)
            if decision is None:
                raise ProgramError(f"the {side} makes no weapon choice in {self.program.name}")
            if option not in decision.options:
                path = self.program.paths[decision]
                raise ProgramError(f"{option} is no option at {path}")
            pinned[decision] = option
        return pinned


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
        try:
            found = self.evaluated.built.fielded[side].part(part)
        except KeyError as error:
            raise ProgramError(f"the {side} fields no part {part}") from error
        return PartAt(self, side, found)


@dataclass(frozen=True)
class PartAt:
    """A part at a step."""

    at: At
    side: Side
    part: Part

    def characteristic(self, c: Characteristic) -> Operand[int | None]:
        """The characteristic in force at the step, read for the role the part plays there.

        Returns:
            The operand, before any rule attached there changes it.

        Raises:
            ProgramError: the step is a decision, which reads no characteristic.
        """
        printed = self.part.characteristic(c)
        step = self.at.step
        spec = self.at.evaluated.built.specs[step]
        if not isinstance(spec, Spec):
            raise ProgramError(f"{self.at.evaluated.lane.program.paths[step]} is a decision")
        role = self.side if Side(step.side) is spec.side else self.side.other
        resolve = spec.in_force.get((role, c))
        value = printed if resolve is None else resolve(self.part)
        return Operand(Distribution.pure(value), printed)


def _parsed[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    try:
        return model.model_validate(yaml.safe_load(path.read_text()))
    except ValidationError as error:
        raise ProgramError(f"{path.name}: {error}") from error


@dataclass(frozen=True)
class _Scope:
    """The steps a read can find: by name and side, and a fighter's group's own by name alone."""

    sides: dict[tuple[str, Side], Step[Any]] = field(default_factory=dict)
    group: dict[str, Step[Any]] | None = None

    def find(self, name: str, side: Side) -> Step[Any] | None:
        if self.group is not None and name in self.group:
            return self.group[name]
        return self.sides.get((name, side))

    def add(self, step: Step[Any], side: Side) -> None:
        if self.group is None:
            self.sides[step.name, side] = step
        else:
            self.group[step.name] = step


type _Groups = dict[tuple[str, Side], list[tuple[Repeat, dict[str, Step[Any]]]]]


@dataclass
class _Builder:
    """Builds a program file's items.

    An entry is built once for each side its ``of`` lists, and a run of slots
    once for each value. A step acting for the side its spec does not swaps
    every role: what it holds, the side facts it reads and writes, and whose
    outputs it reads. A group's fighters fill the attacker's role, so a group
    of the target's fighters swaps the steps inside it. A read finds a step of
    its own group by name, and any other step by name and the side the reader
    acts for: a group's ``times`` by the group's side. With no side fielded, a
    group holds the one fighter None and a decision offers the one option None.
    """

    source: str
    file: ProgramFile
    facts: Mapping[str, StateFact]
    inputs: dict[str, Input]
    fielded: Mapping[Side, Fielding] | None
    states: dict[str, State[Any]] = field(default_factory=dict)
    fighter: tuple[Side, Part | None] | None = None
    swapped: bool = False
    initiative: int | None = None
    slotted: str | None = None
    specs: dict[Step[Any], Spec | Choice] = field(default_factory=dict)
    wielding: dict[Step[Any], tuple[Side, frozenset[str]]] = field(default_factory=dict)
    written: set[str] = field(default_factory=set)

    def build(self) -> Program:
        items = self.block(self.file.items, "items", _Scope())
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
        entries: Iterable[GroupEntry | SlotEntry | SlotsEntry | StepEntry | str],
        where: str,
        visible: _Scope,
    ) -> tuple[Item, ...]:
        groups: _Groups = {}
        built: list[Item] = []
        for index, entry in enumerate(entries):
            here = f"{where}[{index}]"
            if isinstance(entry, SlotsEntry):
                built.extend(self.slots(entry, here, visible))
                continue
            if isinstance(entry, SlotEntry):
                built.append(self.slot(entry, here, visible))
                continue
            if isinstance(entry, GroupEntry):
                built.extend(self.group(entry, of, here, visible, groups) for of in entry.sides)
                continue
            named = StepEntry(step=entry) if isinstance(entry, str) else entry
            built.extend(self.step(named, of, here, visible, groups) for of in named.sides)
        return tuple(built)

    def slots(self, entry: SlotsEntry, here: str, visible: _Scope) -> list[Slot]:
        built: list[Slot] = []
        for value in entry.values:
            self.initiative = value
            items = self.block(entry.items, f"{here}.items", visible)
            built.append(Slot(name=f"{entry.slots}-{value}", items=items))
        self.initiative = None
        return built

    def slot(self, entry: SlotEntry, here: str, visible: _Scope) -> Slot:
        if self.slotted is not None:
            raise self.error(here, f"{entry.slot} is opened inside {self.slotted}")
        self.slotted = entry.slot
        items = self.block(entry.items, f"{here}.items", visible)
        self.slotted = None
        return Slot(name=entry.slot, items=items)

    def role(self, side: Side) -> Side:
        return side.other if self.swapped else side

    def group(
        self, entry: GroupEntry, of: Side, here: str, visible: _Scope, groups: _Groups
    ) -> Sequence:
        times = visible.find(entry.times, of)
        if times is None:
            raise self.error(
                here, f"{entry.group} runs {entry.times} times, which is not in scope"
            )
        if self.fighter is not None:
            raise self.error(here, f"{entry.group} runs inside another fighter's group")
        fighters: tuple[Part | None, ...] = (
            (None,) if self.fielded is None else self.fielded[of].parts
        )
        repeats: list[Repeat] = []
        self.swapped = of is not Side.ATTACKER
        for fighter in fighters:
            self.fighter = (of, fighter)
            own: dict[str, Step[Any]] = {}
            items = self.block(entry.items, f"{here}.items", _Scope(visible.sides, own))
            part = None if fighter is None else fighter.id
            counted = Projection("times", (times.key,), partial(share, part), _ZERO)
            repeat = Repeat(name=part or "fighter", times=counted, items=items)
            groups.setdefault((entry.group, of), []).append((repeat, own))
            repeats.append(repeat)
        self.fighter = None
        self.swapped = False
        return Sequence(name=entry.group, items=tuple(repeats), side=str(of))

    def step(
        self, entry: StepEntry, of: Side | None, here: str, visible: _Scope, groups: _Groups
    ) -> Step[Any]:
        sequence = entry.sequence or self.file.sequence
        spec = SLOTTED.get((self.slotted or "", entry.step)) or STEPS.get((sequence, entry.step))
        if spec is None:
            raise self.error(here, f"{entry.step} is no step of the {sequence} sequence")
        if isinstance(spec, Choice):
            return self.decision(spec, entry, of, here, visible)
        if self.fighter is None:
            self.swapped = of is not None and of is not spec.side
        elif of is not None:
            raise self.error(here, f"{spec.name} takes its side from its group")
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
        acts = self.role(spec.side)
        sided = of is not None
        step = spec.build(kernel, inputs, target, writes, changed, printed, side=acts, sided=sided)
        self.specs[step] = spec
        if self.slotted in AUTOMATIC_HITS:
            self.wielding[step] = (self.role(Side.ATTACKER), frozenset())
        visible.add(step, acts)
        for name in entry.readings:
            offered = spec.readings.get(name)
            if offered is None:
                raise self.error(here, f"{spec.name} offers no reading {name}")
            step.show(self.projection(name, offered, spec, here, visible, tally, changed))
        return step

    def decision(
        self, choice: Choice, entry: StepEntry, of: Side | None, here: str, visible: _Scope
    ) -> Decision[Any]:
        if self.fighter is not None:
            raise self.error(here, f"{choice.name} is decided for a side, not inside a group")
        if entry.readings or entry.tallies:
            raise self.error(here, f"{choice.name} shows no reading and sums no group")
        acts = choice.side if of is None else of
        if acts not in self.file.fielded:
            raise self.error(here, f"{choice.name} decides for the {acts}, which is not fielded")
        options = (None,) if self.fielded is None else choice.options(self.fielded[acts])
        if not options:
            raise self.error(here, f"{choice.name} offers the {acts} nothing to decide")
        decision = Decision[Any](
            name=choice.name,
            side=str(acts),
            sided=of is not None,
            options={option: () for option in options},
            otherwise=options[0],
        )
        self.specs[decision] = choice
        visible.add(decision, acts)
        return decision

    def tally(self, spec: Spec, entry: StepEntry, here: str, groups: _Groups) -> Tally[int] | None:
        if spec.counts is None:
            if entry.tallies:
                raise self.error(here, f"{spec.name} sums no group")
            return None
        if not entry.tallies:
            raise self.error(here, f"{spec.name} needs the groups it tallies")
        counts: dict[Repeat, Projection[int]] = {}
        enemy = self.role(spec.side).other
        for name in entry.tallies:
            tallied = groups.get((name, enemy))
            if tallied is None:
                raise self.error(here, f"{spec.name} tallies {name}, no group before it here")
            for group, own in tallied:
                counts[group] = self.counted(spec.counts, spec, here, _Scope(group=own))
        return Tally(spec.counts.label, counts)

    def counted(self, counts: Counted, spec: Spec, here: str, own: _Scope) -> Projection[int]:
        reads = tuple(self.output(read, spec, here, own) for read in counts.reads)
        return Projection(counts.label, reads, counts.project, _ZERO)

    def projection(
        self,
        label: str,
        offered: Offered,
        spec: Spec,
        here: str,
        visible: _Scope,
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

    def held(
        self, reads: tuple[Read, ...], spec: Spec, here: str
    ) -> tuple[Fielding | Part | int | None, ...]:
        if spec.fighter and self.fighter is None:
            raise self.error(here, f"{spec.name} is made per fighter, outside a fighter's group")
        if not spec.fighter and self.fighter is not None:
            raise self.error(here, f"{spec.name} is made per side, inside a fighter's group")
        values: list[Fielding | Part | int | None] = []
        for read in bound(reads):
            match read:
                case Holding():
                    values.append(self.holding(read, spec, here))
                case Striking():
                    values.append(self.striking(spec, here))
        return tuple(values)

    def striking(self, spec: Spec, here: str) -> int:
        if self.initiative is None:
            raise self.error(here, f"{spec.name} strikes at a slot's Initiative, outside a slot")
        return self.initiative

    def holding(self, read: Holding, spec: Spec, here: str) -> Fielding | Part | None:
        side = self.role(read.of)
        if side not in self.file.fielded:
            raise self.error(
                here, f"{spec.name} reads the {side}, which {self.source} does not field"
            )
        if self.fielded is None:
            return None
        if self.fighter is None:
            return self.fielded[side]
        of, fighter = self.fighter
        return fighter if side is of else self.fielded[side].hit

    def key(
        self,
        read: Read,
        spec: Spec,
        here: str,
        visible: _Scope,
        tally: Tally[int] | None,
        changed: Mark[tuple[Hashable, ...]] | None,
    ) -> Key:
        match read:
            case Holding():
                raise self.error(here, f"{spec.name} reads the {read.of} after another input")
            case Striking():
                raise self.error(here, f"{spec.name} reads its slot after another input")
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

    def output(self, read: Output, spec: Spec, here: str, visible: _Scope) -> Key:
        step = visible.find(read.step, self.role(spec.side if read.of is None else read.of))
        if step is None:
            raise self.error(here, f"{spec.name} reads {read.step}, which is not in scope")
        return step.key

    def facing(self, fact: Fact) -> Fact:
        return fact if fact.of is None else Fact(fact.name, self.role(fact.of))

    def read(self, fact: Fact, spec: Spec, here: str) -> State[Any]:
        name = self.facing(fact).full
        if name in self.inputs:
            return self.inputs[name].state
        if name in self.written:
            return self.states[name]
        raise self.error(here, f"{spec.name} reads {name}, which is no input and is not written")

    def write(self, fact: Fact, here: str) -> State[Any]:
        name = self.facing(fact).full
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
