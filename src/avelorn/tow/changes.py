"""The operations a rule lands on a step, settled in each world.

A payload is what one operation leaves in force at a step. A step's kernel
reads the payloads under its mark through :class:`Payloads`.
"""

from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from avelorn.core.graph import Change, Decision, Key, Order
from avelorn.tow.kernels import Die
from avelorn.tow.schema.effect import Bounded, Effect, Operation, RerollOn
from avelorn.tow.schema.quantity import Quantity
from avelorn.tow.schema.rule import DiceQuantity, Parameter
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.unit import Characteristic

type Changeable = Quantity | Characteristic
type Folded = Quantity | tuple[Side, Characteristic] | RerollOn

_ORDERS = {
    Operation.CANCELS: Order.CANCEL,
    Operation.SET: Order.SET,
    Operation.ADD: Order.ADD,
    Operation.DENY: Order.DENY,
    Operation.FORCE: Order.DENY,
    Operation.SUBSTITUTE: Order.DENY,
    Operation.REROLL: Order.REROLL,
    Operation.MULTIPLY: Order.MULTIPLY,
}


@dataclass(frozen=True)
class Added:
    """An amount added to a quantity, within its printed bounds.

    ``of`` names the side whose model's characteristic it moves, as the step's
    spec names the sides; a quantity has none.
    """

    key: Changeable
    amount: int
    maximum: int | None = None
    minimum: int | None = None
    of: Side | None = None


@dataclass(frozen=True)
class Fixed:
    """A value a quantity is set to; ``of`` reads as on :class:`Added`."""

    key: Changeable
    value: int
    of: Side | None = None


@dataclass(frozen=True)
class Denied:
    """A roll taken away: the step rolls no die."""


@dataclass(frozen=True)
class Rerolled:
    """The dice of a step that a re-roll covers."""

    on: RerollOn


@dataclass(frozen=True)
class Multiplied:
    """What each unsaved wound is multiplied by: a number, or a dice roll made for each wound."""

    by: int | DiceQuantity


@dataclass(frozen=True)
class Forced:
    """The outcomes a step's outcome is forced to."""

    options: frozenset[str]


@dataclass(frozen=True)
class Substituted:
    """Outcomes each replaced by the one it maps to."""

    replaced: tuple[tuple[str, str], ...]


type Payload = Added | Fixed | Denied | Rerolled | Multiplied | Forced | Substituted

_PAYLOADS = (Added, Fixed, Denied, Rerolled, Multiplied, Forced, Substituted)


@dataclass(frozen=True)
class Payloads:
    """The payloads in force at one step."""

    payloads: tuple[Payload, ...]

    @classmethod
    def of(cls, written: tuple[Hashable, ...]) -> "Payloads":
        """Read the payloads a step's mark holds.

        Returns:
            The payloads, in the order they were written.

        Raises:
            TypeError: the mark holds something no kernel folds.
        """
        payloads: list[Payload] = []
        for payload in written:
            if not isinstance(payload, _PAYLOADS):
                raise TypeError(f"{payload!r} is no payload a step folds")
            payloads.append(payload)
        return cls(tuple(payloads))

    def added(self, key: Changeable, of: Side | None = None) -> int:
        """Sum the amounts added to ``key``, of the model ``of`` names for a characteristic.

        Returns:
            The sum, 0 when nothing is added.
        """
        return sum(each.amount for each in self._adds(key, of))

    def bounds(
        self, key: Changeable, of: Side | None = None
    ) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """Read the printed bounds of the amounts added to ``key``, of the model ``of`` names.

        Returns:
            The maxima, then the minima.
        """
        adds = self._adds(key, of)
        maxima = tuple(each.maximum for each in adds if each.maximum is not None)
        minima = tuple(each.minimum for each in adds if each.minimum is not None)
        return maxima, minima

    def fixed(self, key: Changeable, of: Side | None = None) -> tuple[int, ...]:
        """Read the values ``key`` is set to, of the model ``of`` names.

        Returns:
            Every value set, in the order written.
        """
        return tuple(
            each.value
            for each in self.payloads
            if isinstance(each, Fixed) and (each.key, each.of) == (key, of)
        )

    def denied(self) -> bool:
        """Whether a deny is in force.

        Returns:
            True when the step rolls no die.
        """
        return any(isinstance(each, Denied) for each in self.payloads)

    def rerolls(self) -> frozenset[RerollOn]:
        """Read the dice the re-rolls in force cover.

        Returns:
            Each re-roll's dice, once.
        """
        return frozenset(each.on for each in self.payloads if isinstance(each, Rerolled))

    def forced(self) -> str | None:
        """Read the outcome forced.

        Returns:
            The outcome, or None when none is forced.

        Raises:
            ValueError: the outcomes forced are more than one.
        """
        options = frozenset[str]().union(
            *(each.options for each in self.payloads if isinstance(each, Forced))
        )
        if len(options) > 1:
            raise ValueError(f"rules force {', '.join(sorted(options))} at once")
        return next(iter(options), None)

    def substituted(self, outcome: str) -> str:
        """Replace ``outcome`` by each substitution in force, in the order written.

        Returns:
            The outcome left.
        """
        for each in self.payloads:
            if isinstance(each, Substituted):
                outcome = dict(each.replaced).get(outcome, outcome)
        return outcome

    def multiplied(self) -> tuple[int | DiceQuantity, ...]:
        """Read what the unsaved wounds are multiplied by.

        Returns:
            Every multiplier, in the order written.
        """
        return tuple(each.by for each in self.payloads if isinstance(each, Multiplied))

    def _adds(self, key: Changeable, of: Side | None) -> tuple[Added, ...]:
        return tuple(
            each
            for each in self.payloads
            if isinstance(each, Added) and (each.key, each.of) == (key, of)
        )


class Check(Protocol):
    """One condition of a gate; ``consults`` names the rule nodes whose standing it reads."""

    @property
    def reads(self) -> tuple[Key, ...]: ...

    @property
    def consults(self) -> frozenset[str]: ...

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool: ...


@dataclass(frozen=True)
class Constant:
    """A condition the fielding settles."""

    value: bool
    reads: ClassVar[tuple[Key, ...]] = ()
    consults: ClassVar[frozenset[str]] = frozenset()

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        return self.value


@dataclass(frozen=True)
class Shows:
    """A die that landed on a natural face."""

    die: Key
    face: int
    consults: ClassVar[frozenset[str]] = frozenset()

    @property
    def reads(self) -> tuple[Key, ...]:
        """The die's step."""
        return (self.die,)

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        landed = read[self.die]
        return isinstance(landed, Die) and landed.natural == self.face


@dataclass(frozen=True)
class Equals:
    """A step's outcome or a known, equal to a value."""

    fact: Key
    value: Hashable
    consults: ClassVar[frozenset[str]] = frozenset()

    @property
    def reads(self) -> tuple[Key, ...]:
        """The step or known compared."""
        return (self.fact,)

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        return read[self.fact] == self.value


@dataclass(frozen=True)
class Holds:
    """A decision's option, holding every piece of equipment named."""

    option: Key
    held: frozenset[str]
    consults: ClassVar[frozenset[str]] = frozenset()

    @property
    def reads(self) -> tuple[Key, ...]:
        """The decision read."""
        return (self.option,)

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        return self.held <= read[self.option]


@dataclass(frozen=True)
class Uses:
    """How many times each of a side's rules has applied, by rule."""

    counts: tuple[tuple[str, int], ...] = ()

    def of(self, rule: str) -> int:
        """The times ``rule`` has applied.

        Returns:
            The count, 0 for a rule never used.
        """
        return dict(self.counts).get(rule, 0)


@dataclass(frozen=True)
class Unspent:
    """A rule applied fewer times than its limit allows."""

    uses: Key
    rule: str
    times: int
    consults: ClassVar[frozenset[str]] = frozenset()

    @property
    def reads(self) -> tuple[Key, ...]:
        """The uses read."""
        return (self.uses,)

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        return read[self.uses].of(self.rule) < self.times


def _as_read(value: int) -> int:
    return value


@dataclass(frozen=True)
class Measured:
    """A number a gate reads: a known as it is, or one ``measure`` works out from a state."""

    key: Key
    measure: Callable[[Any], int] = _as_read

    def of(self, read: Mapping[Key, Any]) -> int:
        """The number in one world.

        Returns:
            The number.
        """
        return self.measure(read[self.key])


@dataclass(frozen=True)
class MoreThan:
    """A number more than another, or than a fixed one."""

    left: Measured
    right: Measured | int
    consults: ClassVar[frozenset[str]] = frozenset()

    @property
    def reads(self) -> tuple[Key, ...]:
        """What the numbers are read from."""
        right = () if isinstance(self.right, int) else (self.right.key,)
        return tuple(dict.fromkeys((self.left.key, *right)))

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        right = self.right if isinstance(self.right, int) else self.right.of(read)
        return self.left.of(read) > right


@dataclass(frozen=True)
class Granted:
    """One source of a rule node, with the X it gives.

    ``via`` names the node that granted it, and ``weapon`` the weapon it rides
    on when the side chooses which to fight with.
    """

    x: int | str | None
    via: str | None
    weapon: str | None = None


@dataclass(frozen=True)
class Sources:
    """The sources of a rule node at one holder.

    A source riding a weapon is in force only while the bearer's weapon
    ``choice`` holds that weapon; any other source is in force throughout.
    """

    granted: tuple[Granted, ...]
    choice: Decision[Any] | None = None

    @property
    def weapons(self) -> frozenset[str]:
        """The weapons the sources ride on."""
        return frozenset(each.weapon for each in self.granted if each.weapon is not None)

    @property
    def reads(self) -> tuple[Key, ...]:
        """The bearer's choice, when a source rides a weapon."""
        return (self.choice,) if self.choice is not None and self.weapons else ()

    @property
    def consults(self) -> frozenset[str]:
        """The nodes granting the sources."""
        return frozenset(each.via for each in self.granted if each.via is not None)

    def holding(self, held: frozenset[str]) -> tuple[Granted, ...]:
        """The sources in force while the bearer holds ``held``.

        Returns:
            Each source in force.
        """
        return tuple(each for each in self.granted if each.weapon is None or each.weapon in held)

    @property
    def options(self) -> tuple[tuple[Granted, ...], ...]:
        """The sources in force for each option of the choice, or every source with no choice."""
        if self.choice is None or not self.weapons:
            return (self.granted,)
        return tuple(self.holding(option) for option in self.choice.options)

    def in_force(self, read: Mapping[Key, Any], out: frozenset[str]) -> tuple[Granted, ...]:
        """The sources in force in one world: held, and not granted by a node left out.

        Returns:
            Each source in force.
        """
        held = read[self.choice] if self.choice is not None and self.weapons else frozenset()
        return tuple(each for each in self.holding(held) if each.via not in out)

    def at_once(self) -> int:
        """The most sources in force together, over the options of the choice.

        Returns:
            The count.
        """
        return max(len(each) for each in self.options)


@dataclass(frozen=True)
class HasSource:
    """A rule node with a source in force."""

    sources: Sources

    @property
    def reads(self) -> tuple[Key, ...]:
        """What the sources read."""
        return self.sources.reads

    @property
    def consults(self) -> frozenset[str]:
        """The nodes granting the sources."""
        return self.sources.consults

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        return bool(self.sources.in_force(read, out))


@dataclass(frozen=True)
class Attacks:
    """An attack made with a rule of the attacker, while one of its ``sources`` is in force."""

    node: str | None
    wanted: bool
    sources: Sources = Sources(())

    @property
    def reads(self) -> tuple[Key, ...]:
        """What the sources read."""
        return self.sources.reads

    @property
    def consults(self) -> frozenset[str]:
        """The rule attacked with, and the nodes granting its sources."""
        node = frozenset() if self.node is None else frozenset({self.node})
        return node | self.sources.consults

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        attacking = self.node is not None and self.node not in out
        return (attacking and bool(self.sources.in_force(read, out))) is self.wanted


@dataclass(frozen=True)
class Gate:
    """The conditions an effect is gated on.

    Every ``when`` condition must hold. The ``unless`` conditions must not all hold.
    """

    when: tuple[Check, ...] = ()
    unless: tuple[Check, ...] | None = None

    @classmethod
    def folded(cls, when: tuple[Check, ...], unless: tuple[Check, ...] | None) -> "Gate":
        """A gate with every condition the fielding settles folded away.

        Returns:
            The gate, reading only what a world decides.
        """
        never = cls((Constant(False),))
        if Constant(False) in when:
            return never
        live = tuple(check for check in when if not isinstance(check, Constant))
        if unless is None or Constant(False) in unless:
            return cls(live)
        barred = tuple(check for check in unless if not isinstance(check, Constant))
        return cls(live, barred) if barred else never

    @property
    def checks(self) -> tuple[Check, ...]:
        """Every condition of the gate."""
        return (*self.when, *(self.unless or ()))

    @property
    def reads(self) -> tuple[Key, ...]:
        """Every step or known the conditions compare, once each."""
        return tuple(dict.fromkeys(key for check in self.checks for key in check.reads))

    @property
    def consults(self) -> frozenset[str]:
        """Every rule node whose standing a condition reads."""
        return frozenset().union(*(check.consults for check in self.checks))

    def test(self, values: tuple[Any, ...], out: frozenset[str]) -> bool:
        """Whether the gate holds in one world.

        Returns:
            True when the effect is in force there.
        """
        read = dict(zip(self.reads, values, strict=True))
        if not all(check.holds(read, out) for check in self.when):
            return False
        return self.unless is None or not all(check.holds(read, out) for check in self.unless)


@dataclass(frozen=True)
class Operated:
    """One operation of a rule node at a step.

    An add or a set changes one ``key``; a characteristic is the one of the
    model on side ``of``, as the step's spec names the sides. X is the rule's
    parameter combined over the sources in force.
    """

    rule: str
    effect: Effect
    key: Changeable | None
    of: Side | None
    gate: Gate
    sources: Sources
    parameter: Parameter | None

    @property
    def order(self) -> Order:
        """Where the operation applies in the step's printed order."""
        return _ORDERS[self.effect.operation]

    @property
    def reads(self) -> tuple[Key, ...]:
        """What the gate and the sources read."""
        return tuple(dict.fromkeys((*self.gate.reads, *self.sources.reads)))

    @property
    def consults(self) -> frozenset[str]:
        """The rule nodes whose standing the gate and the sources read."""
        return self.gate.consults | self.sources.consults

    def settle(self, values: tuple[Any, ...], out: frozenset[str]) -> Hashable | None:
        """The payload in force in one world.

        Returns:
            The payload, or None when no source is left or the gate fails.
        """
        read = dict(zip(self.reads, values, strict=True))
        left = self.sources.in_force(read, out)
        gated = tuple(read[key] for key in self.gate.reads)
        if not left or not self.gate.test(gated, out):
            return None
        return self.payload(left)

    def payload(self, sources: tuple[Granted, ...]) -> Hashable:
        """The payload the operation leaves with ``sources`` in force.

        Returns:
            An added amount, a value set, a deny, a re-roll, a multiplier, an outcome
            forced or replaced, or the cancel itself.

        Raises:
            ValueError: the operation is not one a step folds.
        """
        effect = self.effect
        match effect.operation:
            case Operation.ADD if effect.add is not None and self.key is not None:
                written = effect.add[self.key]
                if isinstance(written, Bounded):
                    amount = self.amount(written.amount, sources)
                    return Added(self.key, amount, written.maximum, written.minimum, self.of)
                return Added(self.key, self.amount(written, sources), of=self.of)
            case Operation.SET if effect.set_ is not None and self.key is not None:
                return Fixed(self.key, self.amount(effect.set_[self.key], sources), self.of)
            case Operation.DENY if effect.deny:
                return Denied()
            case Operation.REROLL if effect.reroll is not None:
                return Rerolled(effect.reroll)
            case Operation.MULTIPLY if effect.multiply is not None:
                return Multiplied(self.multiplier(effect.multiply, sources))
            case Operation.FORCE if effect.force is not None:
                return Forced(frozenset(effect.force))
            case Operation.SUBSTITUTE if effect.substitute is not None:
                return Substituted(tuple(sorted(effect.substitute.items())))
            case Operation.CANCELS if effect.cancels is not None:
                return effect.cancels
        raise ValueError(f"{self.rule} {effect.operation}s nothing a step folds")

    def amount(self, written: object, sources: tuple[Granted, ...]) -> int:
        """An amount as written, with X combined over ``sources``.

        Returns:
            The amount.

        Raises:
            TypeError: the amount is no number once X is read.
        """
        if written == "X" and self.parameter is not None:
            written = self.parameter.combined([each.x for each in sources if each.x is not None])
        if not isinstance(written, int):
            raise TypeError(f"{self.rule} adds {written!r}, which is no number")
        return written

    def multiplier(self, written: object, sources: tuple[Granted, ...]) -> int | DiceQuantity:
        """A multiplier as written, with X combined over ``sources``.

        Returns:
            The number, or the dice rolled for each wound.

        Raises:
            TypeError: the multiplier is no number and no dice roll once X is read.
        """
        if written == "X" and self.parameter is not None:
            xs = [each.x for each in sources if each.x is not None]
            written = self.parameter.value(self.parameter.combined(xs))
        if not isinstance(written, int | DiceQuantity):
            raise TypeError(f"{self.rule} multiplies by {written!r}, which is no number or roll")
        return written

    def cancels(self, other: Change) -> bool:
        cancels = self.effect.cancels
        return (
            cancels is not None
            and isinstance(other, Operated)
            and other.effect.matches(other.rule, cancels)
            and (cancels.quantity is None or cancels.quantity == other.key)
        )

    def view(self) -> dict[str, Any]:
        """The change as text: one per distinct payload over the options of the choice.

        Returns:
            The text, the payloads joined by "or".
        """
        held = [each for each in self.sources.options if each] or [self.sources.granted]
        texts = dict.fromkeys(self.text(self.payload(each)) for each in held)
        return {"text": " or ".join(texts)}

    def text(self, payload: Hashable) -> str:
        """One payload as text.

        Returns:
            The text.
        """
        match payload:
            case Added(key, amount, maximum, minimum):
                bounds = "".join(
                    f", {name} {bound}"
                    for name, bound in (("at most", maximum), ("at least", minimum))
                    if bound is not None
                )
                return f"{amount:+d} {key}{bounds}"
            case Fixed(key, value):
                return f"{key} {value}"
            case Denied():
                return "deny"
            case Rerolled(on):
                return f"re-roll {on}"
            case Multiplied(by):
                return f"multiply by {by}"
            case Forced(options):
                return f"force {', '.join(sorted(options))}"
            case Substituted(replaced):
                return ", ".join(f"{old} becomes {new}" for old, new in replaced)
        cancels = self.effect.cancels
        named = () if cancels is None else (cancels.rule, cancels.op, cancels.quantity)
        return " ".join(["cancels", *(str(each) for each in named if each is not None)])
