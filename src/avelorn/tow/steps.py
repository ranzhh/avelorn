"""Step registry."""

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import takewhile
from types import MappingProxyType
from typing import Any

from avelorn.core.distribution import Distribution, Kernel, Monoid, Probability
from avelorn.core.graph import (
    Consequence,
    Eligibility,
    Key,
    Mark,
    Measurement,
    Reading,
    Roll,
    State,
    Step,
)
from avelorn.tow.changes import Folded, Payloads
from avelorn.tow.fielding import Fielding, Part, Shots
from avelorn.tow.kernels import (
    HIGH_BALLISTIC_SKILL,
    UNARMOURED,
    Die,
    Standing,
    armour_save_target,
    d6,
    falls_back_in_good_order,
    heavy_casualties,
    leadership_test,
    remove_casualties,
    shooting_hit,
    shooting_hit_target,
    wound_target,
)
from avelorn.tow.schema.effect import Operation, RerollOn
from avelorn.tow.schema.quantity import Quantity
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.step import StepKind, StepSequence
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.schema.weapon import WeaponProfile
from avelorn.tow.traits import Profiled

NO_ROLL = "-"

FRONT_RANK = "front-rank"
HALF_OF_EACH_REAR_RANK = "half-of-each-rear-rank"

_NATURAL = {
    RerollOn.NATURAL_1: 1,
    RerollOn.NATURAL_2: 2,
    RerollOn.NATURAL_3: 3,
    RerollOn.NATURAL_4: 4,
    RerollOn.NATURAL_5: 5,
    RerollOn.NATURAL_6: 6,
}


class Band(StrEnum):
    """Range band."""

    SHORT = "short"
    LONG = "long"
    OUT_OF_RANGE = "out-of-range"


class Test(StrEnum):
    """Panic test result."""

    NOT_TAKEN = "not-taken"
    PASSED = "passed"
    FAILED = "failed"


class Retreat(StrEnum):
    """Retreat after a Panic test."""

    HOLDS = "holds"
    FALLS_BACK_IN_GOOD_ORDER = "falls-back-in-good-order"
    FLEES = "flees"
    DESTROYED = "destroyed"


class Kind(StrEnum):
    """Step kind."""

    MEASUREMENT = "measurement"
    ELIGIBILITY = "eligibility"
    ROLL = "roll"
    CONSEQUENCE = "consequence"

    @property
    def printed(self) -> StepKind:
        """The kind the step table prints; an eligibility is a measurement of who may act."""
        return StepKind.MEASUREMENT if self is Kind.ELIGIBILITY else StepKind(self.value)


@dataclass(frozen=True)
class Fact:
    """A read of a known or state fact."""

    name: str
    of: Side | None = None

    @property
    def full(self) -> str:
        """The fact's name, prefixed by its side when it has one."""
        return self.name if self.of is None else f"{self.of}/{self.name}"


@dataclass(frozen=True)
class Holding:
    """A read of what a side holds at the step, bound when the program is built.

    It comes before every other read of a step or a reading.
    """

    of: Side


@dataclass(frozen=True)
class Output:
    """A read of an earlier step's output, by step name."""

    step: str


@dataclass(frozen=True)
class Summed:
    """A read of a group tally."""


SUMMED = Summed()


@dataclass(frozen=True)
class Changed:
    """A read of the changes in force at the step, always its last input."""


CHANGED = Changed()

type Read = Holding | Fact | Output | Summed | Changed


def holdings(reads: tuple[Read, ...]) -> tuple[Holding, ...]:
    """The holdings that lead ``reads``.

    Returns:
        Each leading holding, in order.

    Raises:
        ValueError: a holding comes after another read.
    """
    leading = tuple(takewhile(lambda read: isinstance(read, Holding), reads))
    if any(isinstance(read, Holding) for read in reads[len(leading) :]):
        raise ValueError(f"{reads}: a holding comes after another read")
    return tuple(read for read in leading if isinstance(read, Holding))


@dataclass(frozen=True)
class Offered:
    """A named reading of a step."""

    reads: tuple[Read, ...]
    project: Callable[..., Hashable]
    aggregation: Monoid[Any]


@dataclass(frozen=True)
class Counted:
    """A per-attack count for a tally."""

    label: str
    reads: tuple[Output, ...]
    project: Callable[..., int]


@dataclass(frozen=True, kw_only=True)
class Spec:
    """A printed step.

    A ``fighter`` step is made once per fighter: its holdings are the fighter's
    part and the part of the model hit. Any other step holds whole sides.
    ``runs`` names what the kernel folds of each operation a rule lands there.
    ``outcomes`` lists every value the step can output. A roll whose rules
    change it shows its ``target`` in force and its ``printed`` target.
    """

    sequence: StepSequence
    name: str
    kind: Kind
    side: Side
    reads: tuple[Read, ...]
    kernel: Kernel[Any]
    target: Offered | None = None
    printed: Offered | None = None
    readings: Mapping[str, Offered] = field(default_factory=dict)
    writes: Fact | None = None
    counts: Counted | None = None
    fighter: bool = False
    in_force: Mapping[tuple[Side, Characteristic], Callable[[Part], int]] = field(
        default_factory=dict
    )
    runs: Mapping[Operation, frozenset[Folded]] = field(default_factory=dict)
    outcomes: frozenset[Hashable] | None = None

    def __post_init__(self) -> None:
        """Refuse an inconsistent spec.

        Raises:
            ValueError: the spec is inconsistent.
        """
        if self.kind is Kind.ROLL and self.target is None:
            raise ValueError(f"{self.name}: a roll needs a target")
        if self.kind is not Kind.ROLL and self.target is not None:
            raise ValueError(f"{self.name}: a {self.kind} shows no target")
        if SUMMED in self.reads and self.counts is None:
            raise ValueError(f"{self.name}: reads a tally it does not count")
        if SUMMED not in self.reads and self.counts is not None:
            raise ValueError(f"{self.name}: counts a tally it does not read")
        if (CHANGED in self.reads) != bool(self.runs):
            raise ValueError(f"{self.name}: reads its changes exactly when it runs some")
        if CHANGED in self.reads[:-1]:
            raise ValueError(f"{self.name}: reads its changes before its last input")
        if (self.printed is not None) != (self.kind is Kind.ROLL and CHANGED in self.reads):
            raise ValueError(f"{self.name}: shows a printed target exactly when rules change it")
        offered = (self.target, self.printed, *self.readings.values())
        for reads in (self.reads, *(each.reads for each in offered if each is not None)):
            holdings(reads)

    @property
    def key(self) -> tuple[StepSequence, str]:
        """The registry key: the sequence and the step name."""
        return self.sequence, self.name

    def build(
        self,
        kernel: Kernel[Any],
        inputs: tuple[Key, ...],
        target: Reading | None,
        writes: State[Any] | None,
        changed: Mark[tuple[Hashable, ...]] | None,
        printed: Reading | None,
    ) -> Step[Any]:
        """Build the step instance from its kernel, with its holdings bound, and its inputs.

        Returns:
            The step, of the class its kind names.

        Raises:
            ValueError: a roll is built with no target.
        """
        side = str(self.side)
        match self.kind:
            case Kind.MEASUREMENT:
                return Measurement(
                    name=self.name,
                    side=side,
                    inputs=inputs,
                    kernel=kernel,
                    writes=writes,
                    changed=changed,
                )
            case Kind.ELIGIBILITY:
                return Eligibility(
                    name=self.name, side=side, inputs=inputs, kernel=kernel, writes=writes
                )
            case Kind.CONSEQUENCE:
                return Consequence(
                    name=self.name,
                    side=side,
                    inputs=inputs,
                    kernel=kernel,
                    writes=writes,
                    changed=changed,
                )
            case Kind.ROLL:
                if target is None:
                    raise ValueError(f"{self.name} rolls with no target shown")
                return Roll(
                    name=self.name,
                    side=side,
                    inputs=inputs,
                    kernel=kernel,
                    writes=writes,
                    target=target,
                    printed=printed,
                    changed=changed,
                )


def _printed(part: Profiled[int | None], c: Characteristic) -> int:
    value = part.characteristic(c)
    if value is None:
        raise ValueError(f"the profile prints '-' for {c.name.replace('_', ' ').title()}")
    return value


def _missile(attacker: Part) -> WeaponProfile:
    if attacker.weapon is None:
        raise ValueError(f"{attacker.id} shoots with no missile weapon")
    return attacker.weapon


def _strength(attacker: Part) -> int:
    strength = _missile(attacker).strength
    if strength.base is not None:
        return strength.base
    return strength.resolve(_printed(attacker, Characteristic.STRENGTH))


def _covers(on: RerollOn, die: Die) -> bool:
    match on:
        case RerollOn.FAILED:
            return not die.success
        case RerollOn.SUCCESSFUL:
            return die.success
    return die.natural == _NATURAL[on]


def _covered(rerolls: frozenset[RerollOn]) -> frozenset[Die]:
    dice = (Die(face, landed) for face in range(1, 7) for landed in (False, True))
    return frozenset(die for die in dice if any(_covers(on, die) for on in rerolls))


def _thrown(target: int, rerolls: frozenset[RerollOn] = frozenset()) -> Distribution[Die | None]:
    landed: dict[Die | None, Probability] = {}
    for die, p in d6(target, _covered(rerolls)).mass.items():
        landed[die] = p
    return Distribution(landed)


def _succeeded(die: Die | None) -> bool:
    return die is not None and die.success


def _shown(target: int | None) -> str:
    return NO_ROLL if target is None else f"{target}+"


@dataclass(frozen=True)
class _Unshown:
    """What a step shows across no attacks."""

    def __str__(self) -> str:
        """No roll, as the rulebook prints it.

        Returns:
            The dash.
        """
        return NO_ROLL


_UNSHOWN = _Unshown()


def _last_unrolled(shown: str) -> tuple[bool, str]:
    return shown == NO_ROLL, shown


def _united(first: Hashable, second: Hashable) -> Hashable:
    if first == _UNSHOWN:
        return second
    if second in (_UNSHOWN, first):
        return first
    shown = {*str(first).split(" or "), *str(second).split(" or ")}
    return " or ".join(sorted(shown, key=_last_unrolled))


def check_range(attacker: Fielding, distance: int) -> Distribution[Band]:
    """Measure the target's distance against the maximum range of the weapons shot.

    Returns:
        The band the target stands in.

    Raises:
        ValueError: the parts shoot weapons of different ranges, or none.
        TypeError: the weapon prints no range in inches.
    """
    reaches = {part.weapon.range for part in attacker.parts if part.weapon is not None}
    if len(reaches) != 1:
        raise ValueError(f"{attacker.unit} must shoot weapons of one range")
    (reach,) = reaches
    if not isinstance(reach, int):
        raise TypeError(f"{attacker.unit} shoots a weapon with no range in inches")
    if distance > reach:
        return Distribution.pure(Band.OUT_OF_RANGE)
    return Distribution.pure(Band.LONG if distance * 2 > reach else Band.SHORT)


def who_can_shoot() -> Distribution[frozenset[str]]:
    """Name the ranks that shoot on flat ground.

    Returns:
        The front rank alone.
    """
    return Distribution.pure(frozenset({FRONT_RANK}))


def how_many_shots(
    attacker: Fielding,
    standing: Standing,
    ranks: frozenset[str],
    can_shoot: bool,
    in_sight: bool,
    band: Band,
) -> Distribution[Shots]:
    """Count each part's shots from the ranks that shoot.

    The models stand in placement order, rank by rank. Half of each rank behind
    the front, rounding up and taken in that order, shoots when Who Can Shoot
    names them.

    Returns:
        The shots of each part.
    """
    fired = dict.fromkeys((part.id for part in attacker.parts), 0)
    if can_shoot and in_sight and band is not Band.OUT_OF_RANGE:
        filled = [
            part for part, models in attacker.standing(standing.models) for _ in range(models)
        ]
        width = attacker.frontage
        for start in range(0, len(filled), width):
            rank = filled[start : start + width]
            if start == 0 and FRONT_RANK in ranks:
                shooting = rank
            elif start > 0 and HALF_OF_EACH_REAR_RANK in ranks:
                shooting = rank[: (len(rank) + 1) // 2]
            else:
                shooting = []
            for part in shooting:
                if part.weapon is not None:
                    fired[part.id] += 1
    return Distribution.pure(Shots(tuple(fired.items())))


def share(part: str | None, shots: Shots) -> int:
    """One part's shots, or every part's when no part is named.

    Returns:
        The shots.
    """
    return shots.total if part is None else shots.of(part)


def _total(shots: Shots) -> int:
    return shots.total


def _hit_needed(attacker: Part, payloads: Payloads) -> str:
    ballistic_skill = _printed(attacker, Characteristic.BALLISTIC_SKILL)
    modifier = payloads.added(Quantity.TO_HIT)
    if ballistic_skill < 6:
        return _shown(shooting_hit_target(ballistic_skill, modifier))
    return f"{2 - modifier}+ then {HIGH_BALLISTIC_SKILL[ballistic_skill]}+"


def roll_to_hit(attacker: Part, changed: tuple[Hashable, ...]) -> Distribution[Die]:
    """Roll one shot To Hit against the shooter's Ballistic Skill, moved by the rules in force.

    Returns:
        The die as it lands.
    """
    modifier = Payloads.of(changed).added(Quantity.TO_HIT)
    return shooting_hit(_printed(attacker, Characteristic.BALLISTIC_SKILL), modifier)


def _wound_target(attacker: Part, target: Part) -> int | None:
    return wound_target(_strength(attacker), _printed(target, Characteristic.TOUGHNESS))


def roll_to_wound(attacker: Part, target: Part, hit: Die) -> Distribution[Die | None]:
    """Roll a hit To Wound, Strength against Toughness.

    Returns:
        The die as it lands, or None when no die is rolled.
    """
    needed = _wound_target(attacker, target)
    if not hit.success or needed is None:
        return Distribution.pure(None)
    return _thrown(needed)


def _save_target(target: Part, attacker: Part, payloads: Payloads) -> int | None:
    piercing = _missile(attacker).armour_piercing - payloads.added(Quantity.ARMOUR_PIERCING)
    armour = UNARMOURED if target.armour is None else target.armour
    maxima, _ = payloads.bounds(Quantity.ARMOUR_VALUE)
    improved = max((armour - payloads.added(Quantity.ARMOUR_VALUE), *maxima))
    return armour_save_target(improved, piercing)


def make_armour_saves(
    target: Part, attacker: Part, wound: Die | None, changed: tuple[Hashable, ...]
) -> Distribution[Die | None]:
    """Roll the armour save against a wound, as the rules in force change it.

    Armour Piercing worsens the save by each amount added to it. The armour
    value improves by each amount added, to no better than the best bound
    printed, and a model with no armour counts as 7+ before it improves.

    Returns:
        The die as it lands, or None when no die is rolled.
    """
    payloads = Payloads.of(changed)
    needed = _save_target(target, attacker, payloads)
    if not _succeeded(wound) or needed is None:
        return Distribution.pure(None)
    return _thrown(needed, payloads.rerolls())


def ward_saves(
    target: Part, wound: Die | None, save: Die | None, changed: tuple[Hashable, ...]
) -> Distribution[Die | None]:
    """Roll the ward save against a wound the armour did not stop.

    A model with more than one ward save uses the best
    (the-shooting-phase/more-than-one-save).

    Returns:
        The die as it lands, or None when no die is rolled.
    """
    ward = _ward(target, Payloads.of(changed))
    if not _succeeded(wound) or _succeeded(save) or ward is None:
        return Distribution.pure(None)
    return _thrown(ward)


def _ward(target: Part, payloads: Payloads) -> int | None:
    printed = () if target.ward is None else (target.ward,)
    return min((*printed, *payloads.fixed(Quantity.WARD_SAVE)), default=None)


def _unsaved(wound: Die | None, save: Die | None, ward: Die | None) -> int:
    return int(_succeeded(wound) and not _succeeded(save) and not _succeeded(ward))


def _remove_casualties(
    target: Fielding, standing: Standing, wounds: int
) -> Distribution[Standing]:
    return Distribution.pure(
        remove_casualties(standing, wounds, _printed(target.hit, Characteristic.WOUNDS))
    )


def _heavy_casualties(standing: Standing, at_start_of_phase: int) -> Distribution[bool]:
    return Distribution.pure(heavy_casualties(standing.models, at_start_of_phase))


def make_panic_tests(
    target: Fielding, standing: Standing, tested: bool, changed: tuple[Hashable, ...]
) -> Distribution[Test]:
    """Take the Panic test on the highest Leadership still standing.

    A failure is re-rolled once when a rule in force allows it.

    Returns:
        The test result.
    """
    if not tested:
        return Distribution.pure(Test.NOT_TAKEN)
    rerolled = RerollOn.FAILED in Payloads.of(changed).rerolls()
    leadership = target.highest(Characteristic.LEADERSHIP, standing.models)
    passes = leadership_test(leadership, rerolled)
    return Distribution({Test.PASSED: passes, Test.FAILED: 1 - passes})


def fall_back_or_flee(
    test: Test, standing: Standing, battle_strength: int
) -> Distribution[Retreat]:
    """Settle a failed Panic test.

    Returns:
        The retreat.
    """
    if standing.models == 0:
        return Distribution.pure(Retreat.DESTROYED)
    if test is not Test.FAILED:
        return Distribution.pure(Retreat.HOLDS)
    if falls_back_in_good_order(standing.models, battle_strength):
        return Distribution.pure(Retreat.FALLS_BACK_IN_GOOD_ORDER)
    return Distribution.pure(Retreat.FLEES)


def _itself[T](value: T) -> T:
    return value


def _models(standing: Standing) -> int:
    return standing.models


def _wounds_lost(standing: Standing) -> int:
    return standing.wounds_lost


def _leadership(target: Fielding, standing: Standing) -> str:
    value = target.highest(Characteristic.LEADERSHIP, standing.models)
    return NO_ROLL if value is None else str(value)


def _landed(die: Die | None) -> int:
    return int(_succeeded(die))


def _listed(ranks: frozenset[str]) -> str:
    return ", ".join(sorted(ranks))


_ATTACKER = Holding(Side.ATTACKER)
_PRINTED = Payloads(())
_TARGET = Holding(Side.TARGET)
_TARGET_STANDING = Fact("standing", Side.TARGET)
_UNITED = Monoid[Hashable](_UNSHOWN, _united)
_COUNT = Monoid(0)
_UNSAVED = (Output("roll-to-wound"), Output("make-armour-saves"), Output("ward-saves"))


def _offer(
    step: str, project: Callable[..., Hashable] = _itself, aggregation: Monoid[Any] = _UNITED
) -> Offered:
    return Offered((Output(step),), project, aggregation)


def _counted(step: str) -> Offered:
    return Offered((Output(step),), _landed, _COUNT)


_SPECS = (
    Spec(
        sequence=StepSequence.SHOOTING,
        name="who-can-shoot",
        kind=Kind.ELIGIBILITY,
        side=Side.ATTACKER,
        reads=(),
        kernel=who_can_shoot,
        readings={"ranks": _offer("who-can-shoot", _listed)},
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="check-range",
        kind=Kind.MEASUREMENT,
        side=Side.ATTACKER,
        reads=(_ATTACKER, Fact("distance")),
        kernel=check_range,
        readings={"band": _offer("check-range")},
        outcomes=frozenset(Band),
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="how-many-shots",
        kind=Kind.MEASUREMENT,
        side=Side.ATTACKER,
        reads=(
            _ATTACKER,
            Fact("standing", Side.ATTACKER),
            Output("who-can-shoot"),
            Fact("can-shoot"),
            Fact("line-of-sight"),
            Output("check-range"),
        ),
        kernel=how_many_shots,
        readings={
            "shots": _offer("how-many-shots", _total, _COUNT),
            "parts": _offer("how-many-shots", str),
        },
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="roll-to-hit",
        kind=Kind.ROLL,
        fighter=True,
        side=Side.ATTACKER,
        reads=(_ATTACKER, CHANGED),
        kernel=roll_to_hit,
        runs={Operation.ADD: frozenset({Quantity.TO_HIT})},
        target=Offered(
            (_ATTACKER, CHANGED),
            lambda attacker, changed: _hit_needed(attacker, Payloads.of(changed)),
            _UNITED,
        ),
        printed=Offered((_ATTACKER,), lambda attacker: _hit_needed(attacker, _PRINTED), _UNITED),
        readings={"hits": _counted("roll-to-hit")},
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="roll-to-wound",
        kind=Kind.ROLL,
        fighter=True,
        side=Side.ATTACKER,
        reads=(_ATTACKER, _TARGET, Output("roll-to-hit")),
        kernel=roll_to_wound,
        in_force={(Side.ATTACKER, Characteristic.STRENGTH): _strength},
        target=Offered(
            (_ATTACKER, _TARGET),
            lambda attacker, target: _shown(_wound_target(attacker, target)),
            _UNITED,
        ),
        readings={"wounds": _counted("roll-to-wound")},
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="make-armour-saves",
        kind=Kind.ROLL,
        fighter=True,
        side=Side.TARGET,
        reads=(_TARGET, _ATTACKER, Output("roll-to-wound"), CHANGED),
        kernel=make_armour_saves,
        runs={
            Operation.ADD: frozenset({Quantity.ARMOUR_PIERCING, Quantity.ARMOUR_VALUE}),
            Operation.REROLL: frozenset(RerollOn),
        },
        target=Offered(
            (_TARGET, _ATTACKER, CHANGED),
            lambda target, attacker, changed: _shown(
                _save_target(target, attacker, Payloads.of(changed))
            ),
            _UNITED,
        ),
        printed=Offered(
            (_TARGET, _ATTACKER),
            lambda target, attacker: _shown(_save_target(target, attacker, _PRINTED)),
            _UNITED,
        ),
        readings={"saves": _counted("make-armour-saves")},
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="ward-saves",
        kind=Kind.ROLL,
        fighter=True,
        side=Side.TARGET,
        reads=(_TARGET, Output("roll-to-wound"), Output("make-armour-saves"), CHANGED),
        kernel=ward_saves,
        runs={Operation.SET: frozenset({Quantity.WARD_SAVE})},
        target=Offered(
            (_TARGET, CHANGED),
            lambda target, changed: _shown(_ward(target, Payloads.of(changed))),
            _UNITED,
        ),
        printed=Offered((_TARGET,), lambda target: _shown(target.ward), _UNITED),
        readings={
            "saves": _counted("ward-saves"),
            "unsaved": Offered(_UNSAVED, _unsaved, _COUNT),
        },
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="remove-casualties",
        kind=Kind.CONSEQUENCE,
        side=Side.TARGET,
        reads=(_TARGET, _TARGET_STANDING, SUMMED),
        kernel=_remove_casualties,
        writes=_TARGET_STANDING,
        counts=Counted("unsaved wounds", _UNSAVED, _unsaved),
        readings={
            "unsaved": Offered((SUMMED,), _itself, _COUNT),
            "models": _offer("remove-casualties", _models, _COUNT),
            "wounds-lost": _offer("remove-casualties", _wounds_lost, _COUNT),
        },
    ),
    Spec(
        sequence=StepSequence.PANIC,
        name="heavy-casualties",
        kind=Kind.MEASUREMENT,
        side=Side.TARGET,
        reads=(_TARGET_STANDING, Fact("models-at-start-of-phase", Side.TARGET)),
        kernel=_heavy_casualties,
        readings={"tested": _offer("heavy-casualties")},
        outcomes=frozenset({True, False}),
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="make-panic-tests",
        kind=Kind.ROLL,
        side=Side.TARGET,
        reads=(_TARGET, _TARGET_STANDING, Output("heavy-casualties"), CHANGED),
        kernel=make_panic_tests,
        runs={Operation.REROLL: frozenset({RerollOn.FAILED})},
        target=Offered((_TARGET, _TARGET_STANDING), _leadership, _UNITED),
        printed=Offered((_TARGET, _TARGET_STANDING), _leadership, _UNITED),
        readings={"test": _offer("make-panic-tests")},
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="fall-back-or-flee",
        kind=Kind.CONSEQUENCE,
        side=Side.TARGET,
        reads=(
            Output("make-panic-tests"),
            _TARGET_STANDING,
            Fact("battle-strength", Side.TARGET),
        ),
        kernel=fall_back_or_flee,
        readings={"retreat": _offer("fall-back-or-flee")},
    ),
)

STEPS: Mapping[tuple[StepSequence, str], Spec] = MappingProxyType(
    {spec.key: spec for spec in _SPECS}
)
