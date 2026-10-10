"""Step registry."""

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from fractions import Fraction
from functools import partial
from itertools import takewhile
from types import MappingProxyType
from typing import Any, ClassVar

from avelorn.core.distribution import Distribution, Kernel, Monoid, Probability
from avelorn.core.graph import (
    Consequence,
    Decision,
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
from avelorn.tow.contingent import ChargeArc
from avelorn.tow.fielding import (
    Attacks,
    Fielding,
    Held,
    Hits,
    Initiatives,
    Part,
    PerPart,
    Shots,
)
from avelorn.tow.kernels import (
    HIGH_BALLISTIC_SKILL,
    UNARMOURED,
    Confirm,
    Die,
    Standings,
    armour_save_target,
    back_rank,
    back_rank_multiplied,
    break_odds,
    d6,
    falls_back_in_good_order,
    heavy_casualties,
    leadership_test,
    melee_hit_target,
    shooting_hit,
    shooting_hit_target,
    wound_target,
)
from avelorn.tow.schema.effect import Operation, RerollOn
from avelorn.tow.schema.quantity import Quantity
from avelorn.tow.schema.rule import DiceQuantity
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.step import StepKind, StepSequence
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.schema.weapon import WeaponProfile
from avelorn.tow.traits import Profiled

NO_ROLL = "-"

FRONT_RANK = "front-rank"
HALF_OF_EACH_REAR_RANK = "half-of-each-rear-rank"
SUPPORTING_ATTACK = "supporting-attack"

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


class Fought(StrEnum):
    """How a round of combat went for one side."""

    WON = "won"
    DRAWN = "drawn"
    LOST = "lost"


class BreakTest(StrEnum):
    """A Break test's result, by the names rules give the printed three."""

    NOT_TAKEN = "not-taken"
    GIVES_GROUND = "gives-ground"
    FALLS_BACK_IN_GOOD_ORDER = "fall-back-in-good-order"
    BREAKS = "breaks"


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
    DECISION = "decision"
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
class Striking:
    """A read of the Initiative the step's slot strikes at, bound when the program is built.

    It comes with the holdings, before every other read.
    """


STRIKING = Striking()


@dataclass(frozen=True)
class Output:
    """A read of an earlier step's output, by step name.

    ``of`` names whose step it is, as the spec names the sides; by default the
    side the spec acts for.
    """

    step: str
    of: Side | None = None


@dataclass(frozen=True)
class Summed:
    """A read of a group tally."""


SUMMED = Summed()


@dataclass(frozen=True)
class Changed:
    """A read of the changes in force at the step, always its last input."""


CHANGED = Changed()

type Bound = Holding | Striking
type Read = Holding | Striking | Fact | Output | Summed | Changed


def bound(reads: tuple[Read, ...]) -> tuple[Bound, ...]:
    """The reads bound when the program is built, which lead ``reads``.

    Returns:
        Each leading bound read, in order.

    Raises:
        ValueError: a bound read comes after another read.
    """
    leading = tuple(takewhile(lambda read: isinstance(read, Holding | Striking), reads))
    if any(isinstance(read, Holding | Striking) for read in reads[len(leading) :]):
        raise ValueError(f"{reads}: a bound read comes after another read")
    return tuple(read for read in leading if isinstance(read, Holding | Striking))


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
    ``runs`` names what the kernel folds of each operation a rule lands there;
    a characteristic it folds is paired with the side whose model it belongs
    to, and a deny or a multiply names nothing, since neither changes a
    quantity. ``outcomes`` lists every value the step can output. A roll whose
    rules change it shows its ``target`` in force and its ``printed`` target.
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
            bound(reads)

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
        *,
        side: Side,
        sided: bool,
    ) -> Step[Any]:
        """Build the step instance from its kernel, with its bound reads bound, and its inputs.

        ``side`` is the side the instance acts for, and ``sided`` marks an
        instance made once per side.

        Returns:
            The step, of the class its kind names.

        Raises:
            ValueError: a roll is built with no target, or a decision from a spec.
        """
        acts = str(side)
        match self.kind:
            case Kind.DECISION:
                raise ValueError(f"{self.name}: a decision is built from a Choice")
            case Kind.MEASUREMENT:
                return Measurement(
                    name=self.name,
                    side=acts,
                    sided=sided,
                    inputs=inputs,
                    kernel=kernel,
                    writes=writes,
                    changed=changed,
                )
            case Kind.ELIGIBILITY:
                return Eligibility(
                    name=self.name,
                    side=acts,
                    sided=sided,
                    inputs=inputs,
                    kernel=kernel,
                    writes=writes,
                    changed=changed,
                )
            case Kind.CONSEQUENCE:
                return Consequence(
                    name=self.name,
                    side=acts,
                    sided=sided,
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
                    side=acts,
                    sided=sided,
                    inputs=inputs,
                    kernel=kernel,
                    writes=writes,
                    target=target,
                    printed=printed,
                    changed=changed,
                )


@dataclass(frozen=True, kw_only=True)
class Choice:
    """A printed decision, made for a side.

    ``options`` names every option from the side when the program is built,
    and the first is the one taken otherwise.
    """

    sequence: StepSequence
    name: str
    side: Side
    options: Callable[[Fielding], tuple[Hashable, ...]]
    kind: ClassVar[Kind] = Kind.DECISION

    @property
    def key(self) -> tuple[StepSequence, str]:
        """The registry key: the sequence and the step name."""
        return self.sequence, self.name


WEAPON_CHOICE = "choose-combat-and-determine-who-can-fight"

AUTOMATIC_HITS = ("impact-hits", "stomp-attacks")


def weapon_choices(specs: Mapping[Step[Any], "Spec | Choice"]) -> dict[Side, Decision[Any]]:
    """The decision each side makes at its weapon choice, by side.

    Returns:
        Each side's weapon choice.

    Raises:
        ValueError: a side makes the choice twice.
    """
    made: dict[Side, Decision[Any]] = {}
    for step, spec in specs.items():
        if isinstance(spec, Choice) and spec.name == WEAPON_CHOICE and isinstance(step, Decision):
            side = Side(step.side)
            if side in made:
                raise ValueError(f"the {side} makes its weapon choice twice")
            made[side] = step
    return made


def _printed(part: Profiled[int | None], c: Characteristic) -> int:
    value = part.characteristic(c)
    if value is None:
        raise ValueError(f"the profile prints '-' for {c.name.replace('_', ' ').title()}")
    return value


def _profile(attacker: Part) -> WeaponProfile:
    if attacker.weapon is None:
        raise ValueError(f"{attacker.id} attacks with no weapon")
    return attacker.weapon


def _moved(part: Part, c: Characteristic, payloads: Payloads, of: Side) -> int:
    role = part.row.role
    match payloads.fixed(c, of, role):
        case ():
            start = _printed(part, c)
        case (fixed,):
            start = fixed
        case fixed:
            raise ValueError(f"{part.id}'s {c} is set {len(fixed)} times")
    maxima, minima = payloads.bounds(c, of, role)
    return min((max((start + payloads.added(c, of, role), *minima)), *maxima))


def _strength(weapon: WeaponProfile, attacker: Part, payloads: Payloads) -> int:
    strength = weapon.strength
    if strength.base is not None:
        return strength.base
    return strength.resolve(_moved(attacker, Characteristic.STRENGTH, payloads, Side.ATTACKER))


def _printed_strength(attacker: Part) -> int:
    return _strength(_profile(attacker), attacker, _PRINTED)


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
    standing: Standings,
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
        filled = [part for part in attacker.parts for _ in range(standing.of(part.id).models)]
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


def share(part: str | None, counted: PerPart) -> int:
    """One part's shots or attacks, or every part's when no part is named.

    Returns:
        The count.
    """
    return counted.total if part is None else counted.of(part)


def _total(counted: PerPart) -> int:
    return counted.total


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


def _wound_target(
    weapon: WeaponProfile, attacker: Part, target: Part, payloads: Payloads
) -> int | None:
    strength = _strength(weapon, attacker, payloads)
    return wound_target(strength, _printed(target, Characteristic.TOUGHNESS))


def _wounded(
    weapon: WeaponProfile, attacker: Part, target: Part, hit: bool, changed: tuple[Hashable, ...]
) -> Distribution[Die | None]:
    payloads = Payloads.of(changed)
    needed = _wound_target(weapon, attacker, target, payloads)
    if not hit or needed is None:
        return Distribution.pure(None)
    return _thrown(needed, payloads.rerolls())


def roll_to_wound(attacker: Part, target: Part, hit: Die) -> Distribution[Die | None]:
    """Roll a hit To Wound, the shot weapon's Strength against Toughness.

    Returns:
        The die as it lands, or None when no die is rolled.
    """
    return _wounded(_profile(attacker), attacker, target, hit.success, ())


def roll_to_wound_in_combat(
    attacker: Part, target: Part, hit: Die, held: Held, changed: tuple[Hashable, ...]
) -> Distribution[Die | None]:
    """Roll a blow To Wound, the Strength of the weapon in ``held`` against Toughness.

    The attacker's Strength moves by each amount added to it, within the
    bounds printed, before its weapon's Strength reads it, and the roll is
    re-rolled as the rules allow.

    Returns:
        The die as it lands, or None when no die is rolled.
    """
    return _wounded(attacker.weapon_with(held), attacker, target, hit.success, changed)


def _front_rank(side: Fielding, at_start: Standings, standing: Standings) -> dict[str, int]:
    placed = [part for part in side.parts for _ in range(at_start.of(part.id).models)]
    front = placed[: side.frontage]
    return {
        part.id: max(
            front.count(part) - at_start.of(part.id).models + standing.of(part.id).models, 0
        )
        for part in side.parts
    }


def automatic_hits(
    attacker: Fielding, at_start: Standings, standing: Standings, changed: tuple[Hashable, ...]
) -> Distribution[Hits]:
    """Roll the automatic hits each part makes, as the rules in force fill the slot.

    Each model of the front rank still standing, the models in base contact
    as the engine reads contact, makes the hits of every rule in force: a
    number or a dice roll each (special-rules/impact-hits,
    special-rules/stomp-attacks). A casualty suffered since the start of the
    round comes off the front rank first. A ridden model's hits are its
    mount's, struck at the mount's Strength
    (troop-types-in-detail/split-profile-cavalry).

    Returns:
        The hits each part makes.
    """
    _since(attacker, at_start, standing)
    each = Distribution.pure(0)
    for per_model in Payloads.of(changed).hits():
        each = each.combine(_rolled(per_model), _COUNT.operation)
    front = _front_rank(attacker, at_start, standing)
    carried = {mount.rider: mount.id for mount in attacker.mounts}
    making = {fighter.id: 0 for fighter in attacker.fighters}
    for part in attacker.parts:
        making[carried.get(part.id, part.id)] = front[part.id]
    made = Distribution.pure(Hits(()))
    for fighter in attacker.fighters:
        theirs = each.repeat(making[fighter.id], _COUNT)
        made = made.bind(partial(_joined, fighter.id, theirs))
    return made


def _joined(part: str, theirs: Distribution[int], made: Hits) -> Distribution[Hits]:
    return theirs.map(lambda count: Hits((*made.parts, (part, count))))


def _hits_shown(changed: tuple[Hashable, ...]) -> str:
    return " + ".join(str(each) for each in Payloads.of(changed).hits()) or NO_ROLL


def _unshown() -> str:
    return NO_ROLL


_BARE = WeaponProfile.model_validate({"R": "Combat", "S": "S"})


def _automatic_wound_target(attacker: Part, target: Part, payloads: Payloads) -> int | None:
    return _wound_target(_BARE, attacker, target, payloads)


def roll_to_wound_automatically(
    attacker: Part, target: Part, changed: tuple[Hashable, ...]
) -> Distribution[Die | None]:
    """Roll an automatic hit To Wound, the model's own Strength against Toughness.

    The hit needs no roll and no weapon strikes it; the Strength moves by the
    rules in force, which the rules that make such hits cancel.

    Returns:
        The die as it lands.
    """
    return _wounded(_BARE, attacker, target, True, changed)


def make_armour_saves_against_automatic_hits(
    target: Part, wound: Die | None, held: Held, changed: tuple[Hashable, ...]
) -> Distribution[Die | None]:
    """Roll the armour save against an automatic hit, which no weapon pierces.

    Returns:
        The die as it lands, or None when no die is rolled.
    """
    return _saved(target.armour_with(held), _BARE, wound, changed)


def _piercing(weapon: WeaponProfile, payloads: Payloads) -> int:
    match payloads.fixed(Quantity.ARMOUR_PIERCING):
        case ():
            printed = weapon.armour_piercing
        case (fixed,):
            printed = -fixed
        case fixed:
            raise ValueError(f"Armour Piercing is set {len(fixed)} times")
    return printed - payloads.added(Quantity.ARMOUR_PIERCING)


def _save_target(worn: int | None, weapon: WeaponProfile, payloads: Payloads) -> int | None:
    if payloads.denied():
        return None
    piercing = _piercing(weapon, payloads)
    armour = UNARMOURED if worn is None else worn
    maxima, _ = payloads.bounds(Quantity.ARMOUR_VALUE)
    improved = max((armour - payloads.added(Quantity.ARMOUR_VALUE), *maxima))
    return armour_save_target(improved, piercing)


def _save_needed(worn: int | None, weapon: WeaponProfile, changed: tuple[Hashable, ...]) -> str:
    return _shown(_save_target(worn, weapon, Payloads.of(changed)))


def _saved(
    worn: int | None, weapon: WeaponProfile, wound: Die | None, changed: tuple[Hashable, ...]
) -> Distribution[Die | None]:
    payloads = Payloads.of(changed)
    needed = _save_target(worn, weapon, payloads)
    if not _succeeded(wound) or needed is None:
        return Distribution.pure(None)
    return _thrown(needed, payloads.rerolls())


def make_armour_saves(
    target: Part, attacker: Part, wound: Die | None, changed: tuple[Hashable, ...]
) -> Distribution[Die | None]:
    """Roll the armour save against a wound, as the rules in force change it.

    Armour Piercing starts from any value set for it, and worsens the save by
    each amount added to it. The armour value improves by each amount added,
    to no better than the best bound printed, and a model with no armour
    counts as 7+ before it improves. A denied save is not rolled.

    Returns:
        The die as it lands, or None when no die is rolled.
    """
    return _saved(target.armour, _profile(attacker), wound, changed)


def make_armour_saves_in_combat(
    target: Part,
    attacker: Part,
    wound: Die | None,
    held: Held,
    striking: Held,
    changed: tuple[Hashable, ...],
) -> Distribution[Die | None]:
    """Roll the armour save against a blow, from the armour the struck side uses with ``held``.

    A shield counts only when held, and the Armour Piercing is the weapon's
    the attacker is ``striking`` with; the rest reads as
    :func:`make_armour_saves`.

    Returns:
        The die as it lands, or None when no die is rolled.
    """
    return _saved(target.armour_with(held), attacker.weapon_with(striking), wound, changed)


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


def _rolled(by: int | DiceQuantity) -> Distribution[int]:
    if isinstance(by, int):
        return Distribution.pure(by)
    return Distribution({face + by.plus: Fraction(1, by.sides) for face in range(1, by.sides + 1)})


def _remove_casualties(
    target: Fielding, standing: Standings, wounds: int, changed: tuple[Hashable, ...]
) -> Distribution[Standings]:
    match Payloads.of(changed).multiplied():
        case ():
            return Distribution.pure(back_rank(standing, wounds, target.removal))
        case (by,):
            return back_rank_multiplied(standing, wounds, _rolled(by), target.removal)
        case many:
            raise ValueError(f"{target.unit}'s unsaved wounds are multiplied {len(many)} times")


def _heavy_casualties(standing: Standings, at_start_of_phase: int) -> Distribution[bool]:
    return Distribution.pure(heavy_casualties(standing.models, at_start_of_phase))


def make_panic_tests(
    target: Fielding, standing: Standings, tested: bool, changed: tuple[Hashable, ...]
) -> Distribution[Test]:
    """Take the Panic test on the highest Leadership still standing.

    A failure is re-rolled once when a rule in force allows it.

    Returns:
        The test result.
    """
    if not tested:
        return Distribution.pure(Test.NOT_TAKEN)
    rerolled = RerollOn.FAILED in Payloads.of(changed).rerolls()
    leadership = target.highest(Characteristic.LEADERSHIP, standing)
    passes = leadership_test(leadership, rerolled)
    return Distribution({Test.PASSED: passes, Test.FAILED: 1 - passes})


def fall_back_or_flee(
    test: Test, standing: Standings, battle_strength: int
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


def _holdings(side: Fielding) -> tuple[Held, ...]:
    return side.hit.holdings


def _rank(number: int) -> str:
    return f"rank-{number}"


def the_charge_move(inches: int) -> Distribution[int]:
    """Measure the full inches a side's charge moved this turn, 0 when it made none.

    Returns:
        The inches.
    """
    return Distribution.pure(inches)


def who_can_fight(changed: tuple[Hashable, ...]) -> Distribution[frozenset[str]]:
    """Name each rank of the fighting rank: the front rank, and one more for each rank added.

    Returns:
        The ranks that fight.
    """
    deep = 1 + Payloads.of(changed).added(Quantity.FIGHTING_RANKS)
    return Distribution.pure(frozenset(_rank(number) for number in range(1, deep + 1)))


def who_strikes_first(
    attacker: Fielding, charged: int, arc: ChargeArc, changed: tuple[Hashable, ...]
) -> Distribution[Initiatives]:
    """Read the Initiative each part strikes at, moved by the rules in force and the charge.

    A value set replaces the printed one before any amount is added, and the
    sum stays within the bounds printed. A side that charged this turn adds a
    point for each full inch it moved, at most the cap of the ``arc`` it
    charged into, and strikes at 10 at most (the-combat-phase/charging-units).

    Returns:
        Each part's Initiative.
    """
    payloads = Payloads.of(changed)
    bonus = min(charged, arc.initiative_cap)
    moved = (
        (
            part.id,
            min(_moved(part, Characteristic.INITIATIVE, payloads, Side.ATTACKER) + bonus, 10),
        )
        for part in attacker.fighters
    )
    return Distribution.pure(Initiatives(tuple(moved)))


def how_many_attacks(
    attacker: Fielding,
    initiative: int,
    ranks: frozenset[str],
    initiatives: Initiatives,
    at_start: Standings,
    standing: Standings,
    changed: tuple[Hashable, ...],
) -> Distribution[Attacks]:
    """Count the attacks of each part that strikes at the slot's Initiative.

    The ranks stand as the side stood ``at_start`` of the round, its models
    placed part by part. Each model in a rank Who Can Fight names makes its
    Attacks, moved by the rules in force. With a supporting attack, each model
    in the rank behind makes one. A casualty suffered since comes off the
    fighting rank first, then the supporting rank, and takes its attacks with
    it (FAQ v1.5.3). A mount makes its own Attacks for each of its rider's
    models in the fighting ranks, and no supporting attack
    (troop-types-in-detail/cavalry-support).

    Returns:
        The attacks of each part.

    Raises:
        ValueError: Who Can Fight names a rank that is not counted, or a part stands
            more models than at the start of the round.
    """
    _since(attacker, at_start, standing)
    fighting = ranks - {SUPPORTING_ATTACK}
    deep = len(fighting)
    if fighting != {_rank(number) for number in range(1, deep + 1)}:
        raise ValueError(f"{attacker.unit} fights with {_listed(ranks)}, which are not counted")
    payloads = Payloads.of(changed)
    width = attacker.frontage
    last = deep + int(SUPPORTING_ATTACK in ranks)
    placed = [part for part in attacker.parts for _ in range(at_start.of(part.id).models)]
    front, support = placed[: deep * width], placed[deep * width : last * width]
    mounted = {mount.rider: mount for mount in attacker.mounts}
    made: dict[str, int] = {}
    for part in attacker.parts:
        lost = at_start.of(part.id).models - standing.of(part.id).models
        in_front = max(front.count(part) - lost, 0)
        supporting = max(support.count(part) - max(lost - front.count(part), 0), 0)
        made[part.id] = _strikes(part, initiatives, initiative, in_front, payloads) + (
            supporting if initiatives.of(part.id) == initiative else 0
        )
        mount = mounted.get(part.id)
        if mount is not None:
            made[mount.id] = _strikes(mount, initiatives, initiative, in_front, payloads)
    return Distribution.pure(Attacks(tuple(made.items())))


def _strikes(
    fighter: Part, initiatives: Initiatives, initiative: int, models: int, payloads: Payloads
) -> int:
    if initiatives.of(fighter.id) != initiative:
        return 0
    return models * _moved(fighter, Characteristic.ATTACKS, payloads, Side.ATTACKER)


def _since(side: Fielding, at_start: Standings, standing: Standings) -> None:
    risen = [
        part.id for part in side.parts if standing.of(part.id).models > at_start.of(part.id).models
    ]
    if risen:
        raise ValueError(f"{side.unit}: {', '.join(risen)} stand more models than at the start")


def _melee_hit_target(attacker: Part, target: Part, payloads: Payloads) -> int:
    return melee_hit_target(
        _moved(attacker, Characteristic.WEAPON_SKILL, payloads, Side.ATTACKER),
        _moved(target, Characteristic.WEAPON_SKILL, payloads, Side.TARGET),
        payloads.added(Quantity.TO_HIT),
    )


def roll_to_hit_in_combat(
    attacker: Part, target: Part, changed: tuple[Hashable, ...]
) -> Distribution[Die]:
    """Roll one attack To Hit, Weapon Skill against the target's on the chart.

    Each Weapon Skill moves by the amounts added to that model's, and the roll
    moves by the rules in force and is re-rolled as they allow.

    Returns:
        The die as it lands; a natural 6 always hits.
    """
    payloads = Payloads.of(changed)
    needed = _melee_hit_target(attacker, target, payloads)
    return d6(needed, _covered(payloads.rerolls()), confirm=Confirm.ALWAYS)


def _itself[T](value: T) -> T:
    return value


def _models(standing: Standings) -> int:
    return standing.models


def _wounds_lost(standing: Standings) -> int:
    return standing.wounds_lost


def _leadership(target: Fielding, standing: Standings) -> str:
    value = target.highest(Characteristic.LEADERSHIP, standing)
    return NO_ROLL if value is None else str(value)


def _landed(die: Die | None) -> int:
    return int(_succeeded(die))


def _listed(ranks: frozenset[str]) -> str:
    return ", ".join(sorted(ranks))


def calculate_combat_result(
    attacker: Fielding,
    target: Fielding,
    standing: Standings,
    enemy_at_start: Standings,
    enemy: Standings,
    arc: ChargeArc,
    changed: tuple[Hashable, ...],
) -> Distribution[int]:
    """Score a side's round: the Wounds it inflicted, its Rank Bonus, and the points rules add.

    The Wounds are those the enemy lost since the start of the round
    (the-combat-phase/unsaved-wounds-inflicted); the Rank Bonus is the one the
    side's standing models claim (the-combat-phase/rank-bonus). A side fighting
    in the enemy's flank or rear claims its points
    (the-combat-phase/flank-and-rear-attacks).

    An enemy part standing more models than at the start of the round fails it.

    Returns:
        The side's combat result.
    """
    _since(target, enemy_at_start, enemy)
    inflicted = target.wounds_left(enemy_at_start) - target.wounds_left(enemy)
    added = Payloads.of(changed).added(Quantity.COMBAT_RESULT)
    bonus = attacker.rank_bonus(standing) + arc.combat_result_bonus
    return Distribution.pure(inflicted + bonus + added)


def who_is_the_winner(
    standing: Standings, enemy: Standings, score: int, enemy_score: int
) -> Distribution[Fought]:
    """Settle how the round went for a side: the higher combat result wins, equal ones draw.

    A side wiped out loses whatever it scored, and two wiped out draw
    (the-combat-phase/calculate-combat-result); the margin stays the difference
    in combat result either way.

    Returns:
        Won, drawn or lost.
    """
    match (standing.models == 0, enemy.models == 0):
        case (True, False):
            return Distribution.pure(Fought.LOST)
        case (False, True):
            return Distribution.pure(Fought.WON)
        case (True, True):
            return Distribution.pure(Fought.DRAWN)
    if score == enemy_score:
        return Distribution.pure(Fought.DRAWN)
    return Distribution.pure(Fought.WON if score > enemy_score else Fought.LOST)


def _lead(score: int, enemy_score: int) -> int:
    return score - enemy_score


def _leadership_in_force(
    side: Fielding, standing: Standings, changed: tuple[Hashable, ...]
) -> int | None:
    value = side.highest(Characteristic.LEADERSHIP, standing)
    added = Payloads.of(changed).added(Characteristic.LEADERSHIP, Side.ATTACKER)
    return None if value is None else value + added


def _leadership_shown(side: Fielding, standing: Standings, changed: tuple[Hashable, ...]) -> str:
    value = _leadership_in_force(side, standing, changed)
    return NO_ROLL if value is None else str(value)


def break_test(
    attacker: Fielding,
    standing: Standings,
    fought: Fought,
    score: int,
    enemy_score: int,
    changed: tuple[Hashable, ...],
) -> Distribution[BreakTest]:
    """Take the Break test of a side that lost the round and still stands.

    It tests the highest Leadership still standing, moved by the rules in
    force, with the difference in combat result added to the roll
    (the-combat-phase/break-test). An outcome a rule forces stands in for the
    roll.

    Returns:
        The result; a side that won, drew or was wiped out takes no test.

    Raises:
        ValueError: no model left standing prints a Leadership.
    """
    if fought is not Fought.LOST or standing.models == 0:
        return Distribution.pure(BreakTest.NOT_TAKEN)
    forced = Payloads.of(changed).forced()
    if forced is not None:
        return Distribution.pure(BreakTest(forced))
    leadership = _leadership_in_force(attacker, standing, changed)
    if leadership is None:
        raise ValueError("no model left standing prints a Leadership to test")
    odds = break_odds(leadership, enemy_score - score)
    return Distribution(
        {
            BreakTest.GIVES_GROUND: odds.gives_ground,
            BreakTest.FALLS_BACK_IN_GOOD_ORDER: odds.falls_back,
            BreakTest.BREAKS: odds.breaks,
        }
    )


def loser_falls_back_in_good_order(
    attacker: Fielding,
    target: Fielding,
    standing: Standings,
    enemy: Standings,
    test: BreakTest,
    changed: tuple[Hashable, ...],
) -> Distribution[BreakTest]:
    """Settle a loser that would Fall Back in Good Order.

    It Breaks instead when the winner's Unit Strength is more than twice its
    own, each counted once the round is fought
    (the-combat-phase/loser-falls-back-in-good-order). An outcome a rule
    forces stands in for that, and a substitution in force then replaces the
    outcome left.

    Returns:
        The result the side acts on.
    """
    if test is not BreakTest.FALLS_BACK_IN_GOOD_ORDER:
        return Distribution.pure(test)
    payloads = Payloads.of(changed)
    forced = payloads.forced()
    if forced is not None:
        settled = BreakTest(forced)
    elif target.unit_strength(enemy) > 2 * attacker.unit_strength(standing):
        settled = BreakTest.BREAKS
    else:
        settled = test
    return Distribution.pure(BreakTest(payloads.substituted(settled)))


_ATTACKER = Holding(Side.ATTACKER)
_PRINTED = Payloads(())
_TARGET = Holding(Side.TARGET)
_TARGET_STANDING = Fact("standing", Side.TARGET)
_HELD = Output(WEAPON_CHOICE)
_STRIKING = Output(WEAPON_CHOICE, Side.ATTACKER)
_SCORES = (Output("calculate-combat-result"), Output("calculate-combat-result", Side.TARGET))
_UNITED = Monoid[Hashable](_UNSHOWN, _united)
_COUNT = Monoid(0)
_UNSAVED = (Output("roll-to-wound"), Output("make-armour-saves"), Output("ward-saves"))


def _offer(
    step: str, project: Callable[..., Hashable] = _itself, aggregation: Monoid[Any] = _UNITED
) -> Offered:
    return Offered((Output(step),), project, aggregation)


def _counted(step: str) -> Offered:
    return Offered((Output(step),), _landed, _COUNT)


_WOUND_NEEDED = Offered(
    (_ATTACKER, _TARGET),
    lambda attacker, target: _shown(_wound_target(_profile(attacker), attacker, target, _PRINTED)),
    _UNITED,
)
_ALL_REROLLS = frozenset(RerollOn)


_SAVE_RUNS: Mapping[Operation, frozenset[Folded]] = MappingProxyType(
    {
        Operation.ADD: frozenset({Quantity.ARMOUR_PIERCING, Quantity.ARMOUR_VALUE}),
        Operation.SET: frozenset({Quantity.ARMOUR_PIERCING}),
        Operation.DENY: frozenset(),
        Operation.REROLL: _ALL_REROLLS,
    }
)


def _shot_saving() -> Spec:
    return Spec(
        sequence=StepSequence.SHOOTING,
        name="make-armour-saves",
        kind=Kind.ROLL,
        fighter=True,
        side=Side.TARGET,
        reads=(_TARGET, _ATTACKER, Output("roll-to-wound"), CHANGED),
        kernel=make_armour_saves,
        runs=_SAVE_RUNS,
        target=Offered(
            (_TARGET, _ATTACKER, CHANGED),
            lambda target, attacker, changed: _save_needed(
                target.armour, _profile(attacker), changed
            ),
            _UNITED,
        ),
        printed=Offered(
            (_TARGET, _ATTACKER),
            lambda target, attacker: _save_needed(target.armour, _profile(attacker), ()),
            _UNITED,
        ),
        readings={"saves": _counted("make-armour-saves")},
    )


def _struck_saving() -> Spec:
    return Spec(
        sequence=StepSequence.COMBAT,
        name="make-armour-saves",
        kind=Kind.ROLL,
        fighter=True,
        side=Side.TARGET,
        reads=(_TARGET, _ATTACKER, Output("roll-to-wound"), _HELD, _STRIKING, CHANGED),
        kernel=make_armour_saves_in_combat,
        runs=_SAVE_RUNS,
        target=Offered(
            (_TARGET, _ATTACKER, _HELD, _STRIKING, CHANGED),
            lambda target, attacker, held, striking, changed: _save_needed(
                target.armour_with(held), attacker.weapon_with(striking), changed
            ),
            _UNITED,
        ),
        printed=Offered(
            (_TARGET, _ATTACKER, _HELD, _STRIKING),
            lambda target, attacker, held, striking: _save_needed(
                target.armour_with(held), attacker.weapon_with(striking), ()
            ),
            _UNITED,
        ),
        readings={"saves": _counted("make-armour-saves")},
    )


def _warding(sequence: StepSequence) -> Spec:
    return Spec(
        sequence=sequence,
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
    )


def _removing(sequence: StepSequence) -> Spec:
    return Spec(
        sequence=sequence,
        name="remove-casualties",
        kind=Kind.CONSEQUENCE,
        side=Side.TARGET,
        reads=(_TARGET, _TARGET_STANDING, SUMMED, CHANGED),
        kernel=_remove_casualties,
        runs={Operation.MULTIPLY: frozenset()},
        writes=_TARGET_STANDING,
        counts=Counted("unsaved wounds", _UNSAVED, _unsaved),
        readings={
            "unsaved": Offered((SUMMED,), _itself, _COUNT),
            "models": _offer("remove-casualties", _models, _COUNT),
            "wounds-lost": _offer("remove-casualties", _wounds_lost, _COUNT),
        },
    )


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
        in_force={(Side.ATTACKER, Characteristic.STRENGTH): _printed_strength},
        target=_WOUND_NEEDED,
        readings={"wounds": _counted("roll-to-wound")},
    ),
    _shot_saving(),
    _warding(StepSequence.SHOOTING),
    _removing(StepSequence.SHOOTING),
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
    Spec(
        sequence=StepSequence.CHARGE,
        name="the-charge-move",
        kind=Kind.CONSEQUENCE,
        side=Side.ATTACKER,
        reads=(Fact("charge-move", Side.ATTACKER),),
        kernel=the_charge_move,
        readings={"inches": _offer("the-charge-move", _itself, _COUNT)},
    ),
    Choice(
        sequence=StepSequence.COMBAT,
        name=WEAPON_CHOICE,
        side=Side.ATTACKER,
        options=_holdings,
    ),
    Spec(
        sequence=StepSequence.COMBAT,
        name="who-can-fight",
        kind=Kind.ELIGIBILITY,
        side=Side.ATTACKER,
        reads=(CHANGED,),
        kernel=who_can_fight,
        runs={Operation.ADD: frozenset({Quantity.FIGHTING_RANKS})},
        readings={"ranks": _offer("who-can-fight", _listed)},
    ),
    Spec(
        sequence=StepSequence.COMBAT,
        name="who-strikes-first",
        kind=Kind.MEASUREMENT,
        side=Side.ATTACKER,
        reads=(_ATTACKER, Output("the-charge-move"), Fact("enemy-arc", Side.ATTACKER), CHANGED),
        kernel=who_strikes_first,
        runs={
            Operation.SET: frozenset({(Side.ATTACKER, Characteristic.INITIATIVE)}),
            Operation.ADD: frozenset({(Side.ATTACKER, Characteristic.INITIATIVE)}),
        },
        readings={"initiatives": _offer("who-strikes-first", str)},
    ),
    *(
        Spec(
            sequence=StepSequence.COMBAT,
            name=name,
            kind=Kind.ROLL,
            side=Side.ATTACKER,
            reads=(
                _ATTACKER,
                Fact("standing-at-start-of-round", Side.ATTACKER),
                Fact("standing", Side.ATTACKER),
                CHANGED,
            ),
            kernel=automatic_hits,
            runs={Operation.HITS: frozenset()},
            target=Offered((CHANGED,), _hits_shown, _UNITED),
            printed=Offered((), _unshown, _UNITED),
            readings={"hits": _offer(name, _total, _COUNT)},
        )
        for name in AUTOMATIC_HITS
    ),
    Spec(
        sequence=StepSequence.COMBAT,
        name="how-many-attacks",
        kind=Kind.MEASUREMENT,
        side=Side.ATTACKER,
        reads=(
            _ATTACKER,
            STRIKING,
            Output("who-can-fight"),
            Output("who-strikes-first"),
            Fact("standing-at-start-of-round", Side.ATTACKER),
            Fact("standing", Side.ATTACKER),
            CHANGED,
        ),
        kernel=how_many_attacks,
        runs={
            Operation.SET: frozenset({(Side.ATTACKER, Characteristic.ATTACKS)}),
            Operation.ADD: frozenset({(Side.ATTACKER, Characteristic.ATTACKS)}),
        },
        readings={
            "attacks": _offer("how-many-attacks", _total, _COUNT),
            "parts": _offer("how-many-attacks", str),
        },
    ),
    Spec(
        sequence=StepSequence.COMBAT,
        name="roll-to-hit",
        kind=Kind.ROLL,
        fighter=True,
        side=Side.ATTACKER,
        reads=(_ATTACKER, _TARGET, CHANGED),
        kernel=roll_to_hit_in_combat,
        runs={
            Operation.ADD: frozenset(
                {
                    Quantity.TO_HIT,
                    (Side.ATTACKER, Characteristic.WEAPON_SKILL),
                    (Side.TARGET, Characteristic.WEAPON_SKILL),
                }
            ),
            Operation.REROLL: _ALL_REROLLS,
        },
        target=Offered(
            (_ATTACKER, _TARGET, CHANGED),
            lambda attacker, target, changed: _shown(
                _melee_hit_target(attacker, target, Payloads.of(changed))
            ),
            _UNITED,
        ),
        printed=Offered(
            (_ATTACKER, _TARGET),
            lambda attacker, target: _shown(_melee_hit_target(attacker, target, _PRINTED)),
            _UNITED,
        ),
        readings={"hits": _counted("roll-to-hit")},
    ),
    Spec(
        sequence=StepSequence.COMBAT,
        name="roll-to-wound",
        kind=Kind.ROLL,
        fighter=True,
        side=Side.ATTACKER,
        reads=(_ATTACKER, _TARGET, Output("roll-to-hit"), _HELD, CHANGED),
        kernel=roll_to_wound_in_combat,
        runs={
            Operation.ADD: frozenset({(Side.ATTACKER, Characteristic.STRENGTH)}),
            Operation.REROLL: _ALL_REROLLS,
        },
        target=Offered(
            (_ATTACKER, _TARGET, _HELD, CHANGED),
            lambda attacker, target, held, changed: _shown(
                _wound_target(attacker.weapon_with(held), attacker, target, Payloads.of(changed))
            ),
            _UNITED,
        ),
        printed=Offered(
            (_ATTACKER, _TARGET, _HELD),
            lambda attacker, target, held: _shown(
                _wound_target(attacker.weapon_with(held), attacker, target, _PRINTED)
            ),
            _UNITED,
        ),
        readings={"wounds": _counted("roll-to-wound")},
    ),
    _struck_saving(),
    _warding(StepSequence.COMBAT),
    _removing(StepSequence.COMBAT),
    Spec(
        sequence=StepSequence.COMBAT_RESULT,
        name="calculate-combat-result",
        kind=Kind.CONSEQUENCE,
        side=Side.ATTACKER,
        reads=(
            _ATTACKER,
            _TARGET,
            Fact("standing", Side.ATTACKER),
            Fact("standing-at-start-of-round", Side.TARGET),
            _TARGET_STANDING,
            Fact("enemy-arc", Side.ATTACKER),
            CHANGED,
        ),
        kernel=calculate_combat_result,
        runs={Operation.ADD: frozenset({Quantity.COMBAT_RESULT})},
        readings={"score": _offer("calculate-combat-result", _itself, _COUNT)},
    ),
    Spec(
        sequence=StepSequence.COMBAT_RESULT,
        name="who-is-the-winner",
        kind=Kind.CONSEQUENCE,
        side=Side.ATTACKER,
        reads=(Fact("standing", Side.ATTACKER), _TARGET_STANDING, *_SCORES),
        kernel=who_is_the_winner,
        readings={
            "result": _offer("who-is-the-winner"),
            "margin": Offered(_SCORES, _lead, _COUNT),
        },
        outcomes=frozenset(Fought),
    ),
    Spec(
        sequence=StepSequence.BREAK,
        name="break-test",
        kind=Kind.ROLL,
        side=Side.ATTACKER,
        reads=(
            _ATTACKER,
            Fact("standing", Side.ATTACKER),
            Output("who-is-the-winner"),
            *_SCORES,
            CHANGED,
        ),
        kernel=break_test,
        runs={
            Operation.ADD: frozenset({(Side.ATTACKER, Characteristic.LEADERSHIP)}),
            Operation.FORCE: frozenset(),
        },
        target=Offered(
            (_ATTACKER, Fact("standing", Side.ATTACKER), CHANGED), _leadership_shown, _UNITED
        ),
        printed=Offered((_ATTACKER, Fact("standing", Side.ATTACKER)), _leadership, _UNITED),
        readings={"test": _offer("break-test")},
        outcomes=frozenset(BreakTest),
    ),
    Spec(
        sequence=StepSequence.BREAK,
        name="loser-falls-back-in-good-order",
        kind=Kind.CONSEQUENCE,
        side=Side.ATTACKER,
        reads=(
            _ATTACKER,
            _TARGET,
            Fact("standing", Side.ATTACKER),
            _TARGET_STANDING,
            Output("break-test"),
            CHANGED,
        ),
        kernel=loser_falls_back_in_good_order,
        runs={Operation.FORCE: frozenset(), Operation.SUBSTITUTE: frozenset()},
        readings={"result": _offer("loser-falls-back-in-good-order")},
        outcomes=frozenset(BreakTest),
    ),
)

STEPS: Mapping[tuple[StepSequence, str], Spec | Choice] = MappingProxyType(
    {spec.key: spec for spec in _SPECS}
)

_HIT_AUTOMATICALLY = (
    Spec(
        sequence=StepSequence.COMBAT,
        name="roll-to-wound",
        kind=Kind.ROLL,
        fighter=True,
        side=Side.ATTACKER,
        reads=(_ATTACKER, _TARGET, CHANGED),
        kernel=roll_to_wound_automatically,
        runs={
            Operation.ADD: frozenset({(Side.ATTACKER, Characteristic.STRENGTH)}),
            Operation.REROLL: _ALL_REROLLS,
        },
        target=Offered(
            (_ATTACKER, _TARGET, CHANGED),
            lambda attacker, target, changed: _shown(
                _automatic_wound_target(attacker, target, Payloads.of(changed))
            ),
            _UNITED,
        ),
        printed=Offered(
            (_ATTACKER, _TARGET),
            lambda attacker, target: _shown(_automatic_wound_target(attacker, target, _PRINTED)),
            _UNITED,
        ),
        readings={"wounds": _counted("roll-to-wound")},
    ),
    Spec(
        sequence=StepSequence.COMBAT,
        name="make-armour-saves",
        kind=Kind.ROLL,
        fighter=True,
        side=Side.TARGET,
        reads=(_TARGET, Output("roll-to-wound"), _HELD, CHANGED),
        kernel=make_armour_saves_against_automatic_hits,
        runs=_SAVE_RUNS,
        target=Offered(
            (_TARGET, _HELD, CHANGED),
            lambda target, held, changed: _save_needed(target.armour_with(held), _BARE, changed),
            _UNITED,
        ),
        printed=Offered(
            (_TARGET, _HELD),
            lambda target, held: _save_needed(target.armour_with(held), _BARE, ()),
            _UNITED,
        ),
        readings={"saves": _counted("make-armour-saves")},
    ),
)

SLOTTED: Mapping[tuple[str, str], Spec] = MappingProxyType(
    {(slot, spec.name): spec for slot in AUTOMATIC_HITS for spec in _HIT_AUTOMATICALLY}
)
