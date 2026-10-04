"""Step registry."""

from collections.abc import Callable, Hashable, Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from avelorn.core.distribution import Distribution, Kernel, Monoid, Probability
from avelorn.core.graph import (
    Consequence,
    Key,
    Mark,
    Measurement,
    Reading,
    Roll,
    Source,
    State,
    Step,
)
from avelorn.tow.changes import Folded, Payloads
from avelorn.tow.contingent import Contingent
from avelorn.tow.engine.armour import defender_armour
from avelorn.tow.kernels import (
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
from avelorn.tow.schema.effect import Operation
from avelorn.tow.schema.quantity import Quantity
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.step import StepSequence
from avelorn.tow.schema.unit import Characteristic, Profile
from avelorn.tow.schema.weapon import Weapon, WeaponProfile
from avelorn.tow.traits import Carries, Profiled

NO_ROLL = "-"


@dataclass(frozen=True, eq=False)
class Fielded:
    """A fielded side as one part, until fielded sides carry their parts."""

    part: str
    row: Profile
    frontage: int
    weapon: WeaponProfile | None = None
    armour: int | None = None
    ward: int | None = None
    wielded: Weapon | None = None
    carried: tuple[tuple[RuleRef, Source], ...] = ()

    def characteristic(self, c: Characteristic) -> int | None:
        """The part's printed value for a characteristic.

        Returns:
            The printed value, or None for a printed "-".
        """
        return self.row.characteristic(c)

    def sources(self) -> Iterator[tuple[RuleRef, Source]]:
        """The rules the side carries into the step, with what gives each.

        Yields:
            The reference, and its source.
        """
        yield from self.carried

    @classmethod
    def of(cls, contingent: Contingent, weapon: str | None = None) -> "Fielded":
        """Field a contingent as one part.

        The armour value folds from the armour worn. A ward comes only from rules,
        so a side fielded from the corpus has none. The side carries the rules of
        its datasheet, its troop type, and the profile its weapon shoots with.

        Returns:
            The fielded side.

        Raises:
            ValueError: ``weapon`` has no missile profile.
        """
        unit = contingent.unit
        carriers: tuple[Carries, ...] = (unit, unit.rank_and_file)
        carried = [pair for carrier in carriers for pair in carrier.sources()]
        wielded = profile = None
        if weapon is not None:
            wielded = contingent.loadout.weapon(weapon)
            profile = wielded.missile_profile
            if profile is None:
                raise ValueError(f"{weapon} has no missile profile; it cannot shoot")
            shot = profile.name or wielded.name
            carried += [pair for pair in wielded.sources() if pair[1].profile == shot]
        return cls(
            part=unit.id,
            row=unit.main,
            frontage=contingent.frontage,
            weapon=profile,
            armour=defender_armour(contingent.loadout.armour),
            wielded=wielded,
            carried=tuple(carried),
        )


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
    ROLL = "roll"
    CONSEQUENCE = "consequence"


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

type Read = Fact | Output | Summed | Changed


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

    ``runs`` names what the kernel folds of each operation a rule lands there.
    ``outcomes`` lists every value the step can output.
    """

    sequence: StepSequence
    name: str
    kind: Kind
    side: Side
    reads: tuple[Read, ...]
    kernel: Kernel[Any]
    target: Offered | None = None
    readings: Mapping[str, Offered] = field(default_factory=dict)
    writes: Fact | None = None
    counts: Counted | None = None
    in_force: Mapping[tuple[Side, Characteristic], Callable[[Fielded], int]] = field(
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

    @property
    def key(self) -> tuple[StepSequence, str]:
        """The registry key: the sequence and the step name."""
        return self.sequence, self.name

    def build(
        self,
        inputs: tuple[Key, ...],
        target: Reading | None,
        writes: State[Any] | None,
        changed: Mark[tuple[Hashable, ...]] | None,
    ) -> Step[Any]:
        """Build the step instance from its resolved inputs.

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
                    kernel=self.kernel,
                    writes=writes,
                    changed=changed,
                )
            case Kind.CONSEQUENCE:
                return Consequence(
                    name=self.name,
                    side=side,
                    inputs=inputs,
                    kernel=self.kernel,
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
                    kernel=self.kernel,
                    writes=writes,
                    target=target,
                    changed=changed,
                )


def _printed(part: Profiled[int | None], c: Characteristic) -> int:
    value = part.characteristic(c)
    if value is None:
        raise ValueError(f"the profile prints '-' for {c.name.replace('_', ' ').title()}")
    return value


def _missile(attacker: Fielded) -> WeaponProfile:
    if attacker.weapon is None:
        raise ValueError(f"{attacker.part} shoots with no missile weapon")
    return attacker.weapon


def _strength(attacker: Fielded) -> int:
    strength = _missile(attacker).strength
    if strength.base is not None:
        return strength.base
    return strength.resolve(_printed(attacker, Characteristic.STRENGTH))


def _thrown(target: int) -> Distribution[Die | None]:
    landed: dict[Die | None, Probability] = {}
    for die, p in d6(target).mass.items():
        landed[die] = p
    return Distribution(landed)


def _succeeded(die: Die | None) -> bool:
    return die is not None and die.success


def _shown(target: int | None) -> str:
    return NO_ROLL if target is None else f"{target}+"


def _agreed(first: Hashable, second: Hashable) -> Hashable:
    if first == NO_ROLL:
        return second
    if second in (NO_ROLL, first):
        return first
    raise ValueError(f"one world holds two targets, {first} and {second}")


def check_range(attacker: Fielded, distance: int) -> Distribution[Band]:
    """Measure the target's distance against the weapon's maximum range.

    Returns:
        The band the target stands in.

    Raises:
        TypeError: the weapon prints no range in inches.
    """
    reach = _missile(attacker).range
    if not isinstance(reach, int):
        raise TypeError(f"{attacker.part} shoots a weapon with no range in inches")
    if distance > reach:
        return Distribution.pure(Band.OUT_OF_RANGE)
    return Distribution.pure(Band.LONG if distance * 2 > reach else Band.SHORT)


def how_many_shots(
    attacker: Fielded, standing: Standing, can_shoot: bool, in_sight: bool, band: Band
) -> Distribution[int]:
    """Count the shots.

    Returns:
        The number of shots.
    """
    if not (can_shoot and in_sight) or band is Band.OUT_OF_RANGE:
        return Distribution.pure(0)
    return Distribution.pure(min(standing.models, attacker.frontage))


def _hit_target(attacker: Fielded) -> int:
    return shooting_hit_target(_printed(attacker, Characteristic.BALLISTIC_SKILL))


def roll_to_hit(attacker: Fielded, changed: tuple[Hashable, ...]) -> Distribution[Die]:
    """Roll one shot To Hit against the shooter's Ballistic Skill, moved by the rules in force.

    Returns:
        The die as it lands.
    """
    modifier = Payloads.of(changed).added(Quantity.TO_HIT)
    return shooting_hit(_printed(attacker, Characteristic.BALLISTIC_SKILL), modifier)


def _wound_target(attacker: Fielded, target: Fielded) -> int | None:
    return wound_target(_strength(attacker), _printed(target, Characteristic.TOUGHNESS))


def roll_to_wound(attacker: Fielded, target: Fielded, hit: Die) -> Distribution[Die | None]:
    """Roll a hit To Wound, Strength against Toughness.

    Returns:
        The die as it lands, or None when no die is rolled.
    """
    needed = _wound_target(attacker, target)
    if not hit.success or needed is None:
        return Distribution.pure(None)
    return _thrown(needed)


def _save_target(target: Fielded, attacker: Fielded) -> int | None:
    return armour_save_target(target.armour, _missile(attacker).armour_piercing)


def make_armour_saves(
    target: Fielded, attacker: Fielded, wound: Die | None
) -> Distribution[Die | None]:
    """Roll the armour save against a wound.

    Returns:
        The die as it lands, or None when no die is rolled.
    """
    needed = _save_target(target, attacker)
    if not _succeeded(wound) or needed is None:
        return Distribution.pure(None)
    return _thrown(needed)


def ward_saves(target: Fielded, wound: Die | None, save: Die | None) -> Distribution[Die | None]:
    """Roll the ward save against a wound the armour did not stop.

    Returns:
        The die as it lands, or None when no die is rolled.
    """
    if not _succeeded(wound) or _succeeded(save) or target.ward is None:
        return Distribution.pure(None)
    return _thrown(target.ward)


def _unsaved(wound: Die | None, save: Die | None, ward: Die | None) -> int:
    return int(_succeeded(wound) and not _succeeded(save) and not _succeeded(ward))


def _remove_casualties(standing: Standing, target: Fielded, wounds: int) -> Distribution[Standing]:
    return Distribution.pure(
        remove_casualties(standing, wounds, _printed(target, Characteristic.WOUNDS))
    )


def _heavy_casualties(standing: Standing, at_start_of_phase: int) -> Distribution[bool]:
    return Distribution.pure(heavy_casualties(standing.models, at_start_of_phase))


def make_panic_tests(target: Fielded, tested: bool) -> Distribution[Test]:
    """Take the Panic test.

    Returns:
        The test result.
    """
    if not tested:
        return Distribution.pure(Test.NOT_TAKEN)
    passes = leadership_test(target.characteristic(Characteristic.LEADERSHIP))
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


def _leadership(target: Fielded) -> str:
    value = target.characteristic(Characteristic.LEADERSHIP)
    return NO_ROLL if value is None else str(value)


def _landed(die: Die | None) -> int:
    return int(_succeeded(die))


_ATTACKER = Fact("fielded", Side.ATTACKER)
_TARGET = Fact("fielded", Side.TARGET)
_TARGET_STANDING = Fact("standing", Side.TARGET)
_AGREED = Monoid[Hashable](NO_ROLL, _agreed)
_COUNT = Monoid(0)
_UNSAVED = (Output("roll-to-wound"), Output("make-armour-saves"), Output("ward-saves"))


def _offer(
    step: str, project: Callable[..., Hashable] = _itself, aggregation: Monoid[Any] = _AGREED
) -> Offered:
    return Offered((Output(step),), project, aggregation)


def _counted(step: str) -> Offered:
    return Offered((Output(step),), _landed, _COUNT)


_SPECS = (
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
            Fact("who-can-shoot"),
            Fact("line-of-sight"),
            Output("check-range"),
        ),
        kernel=how_many_shots,
        readings={"shots": _offer("how-many-shots", aggregation=_COUNT)},
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="roll-to-hit",
        kind=Kind.ROLL,
        side=Side.ATTACKER,
        reads=(_ATTACKER, CHANGED),
        kernel=roll_to_hit,
        runs={Operation.ADD: frozenset({Quantity.TO_HIT})},
        target=Offered((_ATTACKER,), lambda attacker: _shown(_hit_target(attacker)), _AGREED),
        readings={"hits": _counted("roll-to-hit")},
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="roll-to-wound",
        kind=Kind.ROLL,
        side=Side.ATTACKER,
        reads=(_ATTACKER, _TARGET, Output("roll-to-hit")),
        kernel=roll_to_wound,
        in_force={(Side.ATTACKER, Characteristic.STRENGTH): _strength},
        target=Offered(
            (_ATTACKER, _TARGET),
            lambda attacker, target: _shown(_wound_target(attacker, target)),
            _AGREED,
        ),
        readings={"wounds": _counted("roll-to-wound")},
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="make-armour-saves",
        kind=Kind.ROLL,
        side=Side.TARGET,
        reads=(_TARGET, _ATTACKER, Output("roll-to-wound")),
        kernel=make_armour_saves,
        target=Offered(
            (_TARGET, _ATTACKER),
            lambda target, attacker: _shown(_save_target(target, attacker)),
            _AGREED,
        ),
        readings={"saves": _counted("make-armour-saves")},
    ),
    Spec(
        sequence=StepSequence.SHOOTING,
        name="ward-saves",
        kind=Kind.ROLL,
        side=Side.TARGET,
        reads=(_TARGET, Output("roll-to-wound"), Output("make-armour-saves")),
        kernel=ward_saves,
        target=Offered((_TARGET,), lambda target: _shown(target.ward), _AGREED),
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
        reads=(_TARGET_STANDING, _TARGET, SUMMED),
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
        reads=(_TARGET, Output("heavy-casualties")),
        kernel=make_panic_tests,
        target=Offered((_TARGET,), _leadership, _AGREED),
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
