"""The operations a rule lands on a step, settled in each world.

A payload is what one operation leaves in force at a step. A step's kernel
reads the payloads under its mark through :class:`Payloads`.
"""

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from avelorn.core.graph import Change, Key, Order
from avelorn.tow.kernels import Die
from avelorn.tow.schema.effect import Bounded, Effect, Operation, RerollOn
from avelorn.tow.schema.quantity import Quantity
from avelorn.tow.schema.rule import Parameter
from avelorn.tow.schema.unit import Characteristic

type Changeable = Quantity | Characteristic
type Folded = Changeable | RerollOn

_ORDERS = {
    Operation.CANCELS: Order.CANCEL,
    Operation.SET: Order.SET,
    Operation.ADD: Order.ADD,
    Operation.REROLL: Order.REROLL,
}


@dataclass(frozen=True)
class Added:
    """An amount added to a quantity, within its printed bounds."""

    key: Changeable
    amount: int
    maximum: int | None = None
    minimum: int | None = None


@dataclass(frozen=True)
class Fixed:
    """A value a quantity is set to."""

    key: Changeable
    value: int


@dataclass(frozen=True)
class Rerolled:
    """The dice of a step that a re-roll covers."""

    on: RerollOn


type Payload = Added | Fixed | Rerolled


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
            if not isinstance(payload, Added | Fixed | Rerolled):
                raise TypeError(f"{payload!r} is no payload a step folds")
            payloads.append(payload)
        return cls(tuple(payloads))

    def added(self, key: Changeable) -> int:
        """Sum the amounts added to ``key``.

        Returns:
            The sum, 0 when nothing is added.
        """
        return sum(each.amount for each in self._adds(key))

    def bounds(self, key: Changeable) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """Read the printed bounds of the amounts added to ``key``.

        Returns:
            The maxima, then the minima.
        """
        adds = self._adds(key)
        maxima = tuple(each.maximum for each in adds if each.maximum is not None)
        minima = tuple(each.minimum for each in adds if each.minimum is not None)
        return maxima, minima

    def fixed(self, key: Changeable) -> tuple[int, ...]:
        """Read the values ``key`` is set to.

        Returns:
            Every value set, in the order written.
        """
        return tuple(
            each.value for each in self.payloads if isinstance(each, Fixed) and each.key == key
        )

    def rerolls(self) -> frozenset[RerollOn]:
        """Read the dice the re-rolls in force cover.

        Returns:
            Each re-roll's dice, once.
        """
        return frozenset(each.on for each in self.payloads if isinstance(each, Rerolled))

    def _adds(self, key: Changeable) -> tuple[Added, ...]:
        return tuple(each for each in self.payloads if isinstance(each, Added) and each.key == key)


class Check(Protocol):
    """One condition of a gate."""

    @property
    def reads(self) -> tuple[Key, ...]: ...

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool: ...


@dataclass(frozen=True)
class Constant:
    """A condition the fielding settles."""

    value: bool
    reads: ClassVar[tuple[Key, ...]] = ()

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        return self.value


@dataclass(frozen=True)
class Shows:
    """A die that landed on a natural face."""

    die: Key
    face: int

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

    @property
    def reads(self) -> tuple[Key, ...]:
        """The step or known compared."""
        return (self.fact,)

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        return read[self.fact] == self.value


@dataclass(frozen=True)
class MoreThan:
    """A known, more than a number."""

    fact: Key
    value: int

    @property
    def reads(self) -> tuple[Key, ...]:
        """The known compared."""
        return (self.fact,)

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        return read[self.fact] > self.value


@dataclass(frozen=True)
class Attacks:
    """An attack made with a rule of the attacker, or without it."""

    node: str | None
    wanted: bool
    reads: ClassVar[tuple[Key, ...]] = ()

    def holds(self, read: Mapping[Key, Any], out: frozenset[str]) -> bool:
        return (self.node is not None and self.node not in out) is self.wanted


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
class Granted:
    """One source of a rule node, with the X it gives.

    ``via`` names the node that granted it.
    """

    x: int | str | None
    via: str | None


@dataclass(frozen=True)
class Operated:
    """One operation of a rule node at a step.

    An add or a set changes one ``key``. X is the rule's parameter combined over
    the sources still in force.
    """

    rule: str
    effect: Effect
    key: Changeable | None
    gate: Gate
    sources: tuple[Granted, ...]
    parameter: Parameter | None

    @property
    def order(self) -> Order:
        """Where the operation applies in the step's printed order."""
        return _ORDERS[self.effect.operation]

    @property
    def reads(self) -> tuple[Key, ...]:
        """What the gate reads."""
        return self.gate.reads

    def settle(self, values: tuple[Any, ...], out: frozenset[str]) -> Hashable | None:
        """The payload in force in one world.

        Returns:
            The payload, or None when no source is left or the gate fails.
        """
        left = tuple(source for source in self.sources if source.via not in out)
        if not left or not self.gate.test(values, out):
            return None
        return self.payload(left)

    def payload(self, sources: tuple[Granted, ...]) -> Hashable:
        """The payload the operation leaves with ``sources`` in force.

        Returns:
            An added amount, a value set, a re-roll, or the cancel itself.

        Raises:
            ValueError: the operation is not one a step folds.
        """
        effect = self.effect
        match effect.operation:
            case Operation.ADD if effect.add is not None and self.key is not None:
                written = effect.add[self.key]
                if isinstance(written, Bounded):
                    amount = self.amount(written.amount, sources)
                    return Added(self.key, amount, written.maximum, written.minimum)
                return Added(self.key, self.amount(written, sources))
            case Operation.SET if effect.set_ is not None and self.key is not None:
                return Fixed(self.key, self.amount(effect.set_[self.key], sources))
            case Operation.REROLL if effect.reroll is not None:
                return Rerolled(effect.reroll)
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

    def cancels(self, other: Change) -> bool:
        cancels = self.effect.cancels
        return (
            cancels is not None
            and isinstance(other, Operated)
            and other.effect.matches(other.rule, cancels)
            and (cancels.quantity is None or cancels.quantity == other.key)
        )

    def view(self) -> dict[str, Any]:
        payload = self.payload(self.sources)
        match payload:
            case Added(key, amount, maximum, minimum):
                bounds = "".join(
                    f", {name} {bound}"
                    for name, bound in (("at most", maximum), ("at least", minimum))
                    if bound is not None
                )
                return {"text": f"{amount:+d} {key}{bounds}"}
            case Fixed(key, value):
                return {"text": f"{key} {value}"}
            case Rerolled(on):
                return {"text": f"re-roll {on}"}
        cancels = self.effect.cancels
        named = () if cancels is None else (cancels.rule, cancels.op, cancels.quantity)
        return {"text": " ".join(["cancels", *(str(each) for each in named if each is not None)])}
