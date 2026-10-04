"""A rule effect as the graph reads it: where it triggers, where it lands, what it does.

An effect names its landing under ``at``: a printed step and the role acting
there, relative to the bearer. ``when`` holds its trigger and gates, ``unless``
holds gates that must settle false, and the effect carries exactly one
operation, optionally under a ``limit``. A grant names who receives it under
``to`` and has no landing of its own: the granted rule's effects carry theirs.
Every model is strict, so an unknown key fails the load.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from itertools import combinations
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from avelorn.core.graph import Side as Role
from avelorn.tow.schema.quantity import Quantity
from avelorn.tow.schema.reference import RuleRef, Slug
from avelorn.tow.schema.step import Step, StepKind, StepSequence
from avelorn.tow.schema.unit import Characteristic, TroopType
from avelorn.tow.schema.weapon import WeaponType

_STRICT = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

Key = Quantity | Characteristic


class FactRef(BaseModel):
    """A fact read where the effect lands, relative to the bearer when it belongs to a side.

    A fact is a state fact, a step's output named by the step, a derived fact
    or a characteristic.
    """

    model_config = _STRICT

    fact: Slug | Characteristic
    of: Role | None = None


Amount = int | Literal["X"] | FactRef
Value = bool | int | str | FactRef


class Comparison(BaseModel):
    """One comparator and the value it compares against."""

    model_config = _STRICT

    is_: Value | None = Field(default=None, alias="is")
    at_least: Value | None = Field(default=None, alias="at-least")
    at_most: Value | None = Field(default=None, alias="at-most")
    more_than: Value | None = Field(default=None, alias="more-than")

    @model_validator(mode="after")
    def _compares_once(self) -> Self:
        values = (self.is_, self.at_least, self.at_most, self.more_than)
        if sum(value is not None for value in values) != 1:
            raise ValueError("a comparison names exactly one of: is, at-least, at-most, more-than")
        return self


class FactGate(Comparison):
    """A fact compared against a value."""

    fact: Slug | Characteristic
    of: Role | None = None


class WeaponGate(BaseModel):
    """The weapon the sequence is fought or shot with, by family or by slug."""

    model_config = _STRICT

    type: WeaponType | None = None
    weapon: Slug | None = None

    @model_validator(mode="after")
    def _asks_something(self) -> Self:
        if self.type is None and self.weapon is None:
            raise ValueError("a weapon gate names a type or a weapon")
        return self


class ArmourGate(BaseModel):
    """A piece of armour in use, after bars."""

    model_config = _STRICT

    armour: Slug


class AttackGate(BaseModel):
    """What the attack is, read from the attacking fighter's sources."""

    model_config = _STRICT

    magical: bool | None = None
    flaming: bool | None = None

    @model_validator(mode="after")
    def _asks_something(self) -> Self:
        if self.magical is None and self.flaming is None:
            raise ValueError("an attack gate names magical or flaming")
        return self


class FoeGate(BaseModel):
    """The enemy model, by troop type, army or a rule it has."""

    model_config = _STRICT

    troop_type: Annotated[tuple[TroopType, ...], Field(min_length=1)] | None = None
    army: Slug | None = None
    has: Annotated[tuple[Slug, ...], Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def _asks_something(self) -> Self:
        if self.troop_type is None and self.army is None and self.has is None:
            raise ValueError("a foe gate names a troop type, an army or a rule")
        return self


class Carrier(StrEnum):
    """What carries a rule (what-special-rules-does-it-have)."""

    MODEL = "model"
    WEAPON = "weapon"
    ARMOUR = "armour"
    ITEM = "item"
    EFFECT = "effect"
    CORE = "core"


class Gates(BaseModel):
    """The gates an effect reads, all of which hold together."""

    model_config = _STRICT

    with_: WeaponGate | None = Field(default=None, alias="with")
    worn: ArmourGate | None = None
    carried_by: Carrier | None = None
    attack: AttackGate | None = None
    foe: FoeGate | None = None
    facts: tuple[FactGate, ...] = ()

    @property
    def gated(self) -> bool:
        """Whether any gate is set."""
        return any((self.with_, self.worn, self.carried_by, self.attack, self.foe, self.facts))


class Unless(Gates):
    """Gates that must settle false."""

    @model_validator(mode="after")
    def _gates_something(self) -> Self:
        if not self.gated:
            raise ValueError("an unless names at least one gate")
        return self


class When(Gates):
    """A trigger and gates: the step whose outcome fires the effect, and what must hold.

    The trigger is ``step`` and ``by``, and optionally the ``natural`` face its
    die shows, the outcome it ``is``, or the score it ``needed``.
    """

    step: Step | None = None
    by: Role | None = None
    natural: int | None = Field(default=None, ge=1, le=6)
    is_: Value | None = Field(default=None, alias="is")
    needed: Comparison | None = None

    @model_validator(mode="after")
    def _triggers_or_gates(self) -> Self:
        if (self.step is None) != (self.by is None):
            raise ValueError("a trigger names its step and who acts there")
        if self.step is None:
            if self.natural is not None or self.is_ is not None or self.needed is not None:
                raise ValueError("natural, is and needed read a trigger's step")
            if not self.gated:
                raise ValueError("a when names a trigger or a gate")
        elif (self.natural is not None or self.needed is not None) and (
            self.step.kind is not StepKind.ROLL
        ):
            raise ValueError(f"{self.step} rolls no die to read natural or needed from")
        return self


class Address(BaseModel):
    """A printed step and the role acting there, optionally narrowed to a block on its path.

    ``in`` and ``not_in`` name a sequence the step is printed in, or a step
    whose block encloses it, as a Stand & Shoot volley sits in stand-and-shoot.
    """

    model_config = _STRICT

    step: Step
    by: Role
    in_: StepSequence | Step | None = Field(default=None, alias="in")
    not_in: StepSequence | Step | None = None

    @model_validator(mode="after")
    def _narrows_to_somewhere(self) -> Self:
        for name, block in (("in", self.in_), ("not_in", self.not_in)):
            if isinstance(block, StepSequence) and block not in self.step.sequences:
                raise ValueError(f"{name}: {self.step} is not printed in {block}")
        if self.in_ is not None and self.in_ == self.not_in:
            raise ValueError(f"in and not_in both name {self.in_}")
        if not self.sequences:
            raise ValueError(f"not_in: {self.step} is printed in no other sequence")
        return self

    @property
    def sequences(self) -> tuple[StepSequence, ...]:
        """The sequences the address can land in."""
        return tuple(
            sequence
            for sequence in self.step.sequences
            if (not isinstance(self.in_, StepSequence) or sequence == self.in_)
            and sequence != self.not_in
        )

    def overlaps(self, other: "Address") -> bool:
        """Whether one step instance can match both addresses.

        Returns:
            True when both name one step and role and their blocks can meet.
        """
        return (
            self.step == other.step
            and self.by == other.by
            and bool(set(self.sequences) & set(other.sequences))
            and (self.in_ is None or self.in_ != other.not_in)
            and (other.in_ is None or other.in_ != self.not_in)
        )

    def __str__(self) -> str:
        """The address as a sentence.

        Returns:
            The step, the role, and any block it is narrowed to.
        """
        narrowed = "" if self.in_ is None else f" in {self.in_}"
        excluded = "" if self.not_in is None else f" not in {self.not_in}"
        return f"{self.step} by {self.by}{narrowed}{excluded}"


class Bounded(BaseModel):
    """An amount with the printed bound on the value it moves."""

    model_config = _STRICT

    amount: Amount
    maximum: int | None = None
    minimum: int | None = None

    @model_validator(mode="after")
    def _carries_a_bound(self) -> Self:
        if self.maximum is None and self.minimum is None:
            raise ValueError("a bounded amount needs a maximum or a minimum; write it plainly")
        return self


class RerollOn(StrEnum):
    """Which dice at the landing a re-roll covers, by result or by natural face."""

    FAILED = "failed"
    SUCCESSFUL = "successful"
    NATURAL_1 = "natural-1"
    NATURAL_2 = "natural-2"
    NATURAL_3 = "natural-3"
    NATURAL_4 = "natural-4"
    NATURAL_5 = "natural-5"
    NATURAL_6 = "natural-6"


class Operation(StrEnum):
    """What an effect does where it lands."""

    ADD = "add"
    SET = "set"
    REROLL = "reroll"
    DENY = "deny"
    FORCE = "force"
    SUBSTITUTE = "substitute"
    ALLOW = "allow"
    FORBID = "forbid"
    BAR = "bar"
    FILL = "fill"
    HITS = "hits"
    MULTIPLY = "multiply"
    GRANTS = "grants"
    CANCELS = "cancels"


class Cancels(BaseModel):
    """Which effects landing on the canceller's own address are removed."""

    model_config = _STRICT

    rule: Slug | None = None
    op: Operation | None = None
    quantity: Key | None = None

    @model_validator(mode="after")
    def _matches_something(self) -> Self:
        if self.rule is None and self.op is None and self.quantity is None:
            raise ValueError("a cancel names a rule, an operation or a quantity")
        return self


class Period(StrEnum):
    """What a limit counts uses over."""

    GAME = "game"
    TURN = "turn"
    ROUND = "round"


class Limit(BaseModel):
    """How many times an effect may apply over a period."""

    model_config = _STRICT

    per: Period
    times: int = Field(ge=1)


_ATTRIBUTES = {Operation.SET: "set_"}

Options = Annotated[tuple[Slug, ...], Field(min_length=1)]


class Effect(BaseModel):
    """One printed effect: its trigger and gates, its landing, and one operation.

    ``of`` names whose characteristic an add or set changes, since a step reads
    the characteristics of both models at once.
    """

    model_config = _STRICT

    when: When | None = None
    unless: Unless | None = None
    add: Annotated[dict[Key, Amount | Bounded], Field(min_length=1)] | None = None
    set_: Annotated[dict[Key, Amount], Field(min_length=1)] | None = Field(
        default=None, alias="set"
    )
    reroll: RerollOn | None = None
    deny: Literal[True] | None = None
    force: Options | None = None
    substitute: Annotated[dict[Slug, Slug], Field(min_length=1)] | None = None
    allow: Options | None = None
    forbid: Options | None = None
    bar: Slug | None = None
    fill: Literal[True] | None = None
    hits: Amount | None = None
    multiply: Amount | None = None
    grants: RuleRef | None = None
    cancels: Cancels | None = None
    of: Role | None = None
    to: Role | None = None
    at: Address | None = None
    limit: Limit | None = None

    @property
    def operation(self) -> Operation:
        """The one operation the effect carries."""
        (operation,) = (op for op in Operation if self._value(op) is not None)
        return operation

    def _value(self, operation: Operation) -> object:
        return getattr(self, _ATTRIBUTES.get(operation, operation.value))

    @property
    def keys(self) -> frozenset[Key]:
        """The quantities an add or a set changes."""
        return frozenset({*(self.add or {}), *(self.set_ or {})})

    @property
    def _amounts(self) -> tuple[Amount, ...]:
        written = [
            *(self.add or {}).values(),
            *(self.set_ or {}).values(),
            self.hits,
            self.multiply,
        ]
        return tuple(
            amount.amount if isinstance(amount, Bounded) else amount
            for amount in written
            if amount is not None
        )

    @property
    def _gates(self) -> tuple[Gates, ...]:
        return tuple(gates for gates in (self.when, self.unless) if gates is not None)

    @property
    def reads_x(self) -> bool:
        """Whether an amount of the operation is the rule's X."""
        return "X" in self._amounts

    @property
    def facts(self) -> frozenset[str]:
        """Every fact the effect reads, by name."""
        compared = [gate for gates in self._gates for gate in gates.facts]
        values = [
            *self._amounts,
            *(c.is_ for c in compared),
            *(c.at_least for c in compared),
            *(c.at_most for c in compared),
            *(c.more_than for c in compared),
        ]
        named = {gate.fact for gate in compared}
        return frozenset(named | {value.fact for value in values if isinstance(value, FactRef)})

    @property
    def rules(self) -> frozenset[str]:
        """Every rule the effect names: one it grants, cancels, or asks the foe to have."""
        foes = [gates.foe for gates in self._gates if gates.foe is not None]
        named = {rule for foe in foes for rule in foe.has or ()}
        if self.grants is not None:
            named.add(self.grants.rule)
        if self.cancels is not None and self.cancels.rule is not None:
            named.add(self.cancels.rule)
        return frozenset(named)

    @property
    def weapons(self) -> frozenset[str]:
        """Every weapon the effect's gates name."""
        named = [gates.with_.weapon for gates in self._gates if gates.with_ is not None]
        return frozenset(weapon for weapon in named if weapon is not None)

    @property
    def armour(self) -> frozenset[str]:
        """Every piece of armour the effect's gates or its bar name."""
        named = {gates.worn.armour for gates in self._gates if gates.worn is not None}
        return frozenset(named if self.bar is None else {*named, self.bar})

    def matches(self, rule: str, cancels: Cancels) -> bool:
        """Whether a cancel removes this effect of ``rule``.

        Returns:
            True when every part the cancel names matches.
        """
        return (
            (cancels.rule is None or cancels.rule == rule)
            and (cancels.op is None or cancels.op is self.operation)
            and (cancels.quantity is None or cancels.quantity in self.keys)
        )

    @model_validator(mode="after")
    def _one_operation(self) -> Self:
        carried = [op for op in Operation if self._value(op) is not None]
        if len(carried) != 1:
            named = ", ".join(carried) or "none"
            raise ValueError(f"an effect carries exactly one operation; this one carries {named}")
        return self

    @model_validator(mode="after")
    def _lands_or_is_granted(self) -> Self:
        if self.grants is not None:
            if self.to is None or self.at is not None:
                raise ValueError("a grant names who receives it with to, and no landing")
        elif self.at is None or self.to is not None:
            raise ValueError("an effect lands at an address; only a grant names to")
        return self

    @model_validator(mode="after")
    def _owns_a_characteristic(self) -> Self:
        changes_one = any(isinstance(key, Characteristic) for key in self.keys)
        if changes_one != (self.of is not None):
            raise ValueError("of names whose characteristic an add or set changes, and only that")
        return self

    @model_validator(mode="after")
    def _gate_reads_another_step(self) -> Self:
        if self.when is not None and self.at is not None and self.when.step == self.at.step:
            raise ValueError(f"a trigger never names its own landing, {self.at.step}")
        return self

    @model_validator(mode="after")
    def _counts_something(self) -> Self:
        if isinstance(self.hits, int) and self.hits < 1:
            raise ValueError("hits lands at least one hit")
        if isinstance(self.multiply, int) and self.multiply < 2:
            raise ValueError("multiplying by less than 2 says nothing")
        return self

    @model_validator(mode="after")
    def _denies_a_roll(self) -> Self:
        if self.deny and self.at is not None and self.at.step.kind is not StepKind.ROLL:
            raise ValueError(f"deny takes away a roll; {self.at.step} is a {self.at.step.kind}")
        return self


_BEST = frozenset({Quantity.WARD_SAVE})


def conflicts(rules: Mapping[str, Sequence[Effect]]) -> list[str]:
    """Every pair of rules that set one value, or force different options, at one address.

    Two such rules conflict unless either cancels the other there. A Ward save
    is no conflict: a model with more than one uses the best
    (the-shooting-phase/more-than-one-save).

    Returns:
        One message per conflict, naming both rules and the address.
    """
    found = []
    for (first, ours), (second, theirs) in combinations(sorted(rules.items()), 2):
        for mine in ours:
            for other in theirs:
                if mine.at is None or other.at is None or not mine.at.overlaps(other.at):
                    continue
                clash = _clash(mine, other)
                if clash is None or _cancelled(first, mine, ours, second, other, theirs):
                    continue
                found.append(f"{first} and {second} {clash} at {mine.at}, and neither cancels")
    return found


def _clash(mine: Effect, other: Effect) -> str | None:
    shared = sorted(str(key) for key in set(mine.set_ or {}) & set(other.set_ or {}) - _BEST)
    if shared and mine.of == other.of:
        return f"both set {', '.join(shared)}"
    if mine.force is not None and other.force is not None and set(mine.force) != set(other.force):
        return f"force {', '.join(mine.force)} against {', '.join(other.force)}"
    return None


def _cancelled(
    first: str,
    mine: Effect,
    ours: Sequence[Effect],
    second: str,
    other: Effect,
    theirs: Sequence[Effect],
) -> bool:
    return any(
        cancel.cancels is not None
        and cancel.at is not None
        and cancel.at.overlaps(target.at)
        and target.matches(rule, cancel.cancels)
        for cancellers, rule, target in ((ours, second, other), (theirs, first, mine))
        for cancel in cancellers
        if target.at is not None
    )
