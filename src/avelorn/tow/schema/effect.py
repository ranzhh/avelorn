"""A rule effect as the graph reads it.

An effect names its landing under ``at``: a printed step and the role acting
there, relative to the bearer. ``when`` holds its trigger and gates, ``unless``
holds gates that must settle false, and the effect carries exactly one
operation, optionally under a ``limit``. A grant names who or which weapon
receives it under ``to`` and has no landing of its own: the granted rule's
effects carry theirs.
Every model is strict, so an unknown key fails the load.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from itertools import combinations
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from avelorn.core.graph import Carrier
from avelorn.tow.schema.quantity import Quantity
from avelorn.tow.schema.reference import RuleRef, Slug
from avelorn.tow.schema.step import BLOCKS, Step, StepKind, StepSequence
from avelorn.tow.schema.unit import Characteristic, TroopType
from avelorn.tow.schema.weapon import WeaponType

_STRICT = ConfigDict(extra="forbid", frozen=True)


class Role(StrEnum):
    """Who acts at a step, relative to the model whose rule it is."""

    THIS_MODEL = "this-model"
    THE_ENEMY = "the-enemy"


_OTHER = {Role.THIS_MODEL: Role.THE_ENEMY, Role.THE_ENEMY: Role.THIS_MODEL}

Key = Quantity | Characteristic


class FactRef(BaseModel):
    """A fact read where the effect lands, relative to the bearer when it belongs to a side.

    A fact is a state fact, a step's output named by the step, a derived fact
    or a characteristic.
    """

    model_config = _STRICT

    fact: Slug | Characteristic
    of: Role | None = None

    @model_validator(mode="after")
    def _step_names_its_side(self) -> Self:
        _owned(self.fact, self.of)
        return self


def _owned(fact: str, of: Role | None) -> None:
    if fact in Step and of is None:
        raise ValueError(f"{fact} is a step's output, so of names whose step it is")


Amount = StrictInt | Literal["X"] | FactRef
Value = StrictBool | StrictInt | StrictStr | FactRef


class Comparison(BaseModel):
    """One comparator and the value it compares against."""

    model_config = _STRICT

    is_: Value | None = Field(default=None, alias="is")
    at_least: Value | None = Field(default=None, alias="at-least")
    at_most: Value | None = Field(default=None, alias="at-most")
    more_than: Value | None = Field(default=None, alias="more-than")

    @property
    def compared(self) -> tuple[str, "Value"]:
        """The comparator as written, with the value it compares against."""
        written = (
            ("is", self.is_),
            ("at-least", self.at_least),
            ("at-most", self.at_most),
            ("more-than", self.more_than),
        )
        (pair,) = ((name, value) for name, value in written if value is not None)
        return pair

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

    @model_validator(mode="after")
    def _step_names_its_side(self) -> Self:
        _owned(self.fact, self.of)
        return self


class WeaponMatch(BaseModel):
    """A weapon, named by its family or its slug."""

    model_config = _STRICT

    type: WeaponType | None = None
    weapon: Slug | None = None

    @model_validator(mode="after")
    def _asks_something(self) -> Self:
        if self.type is None and self.weapon is None:
            raise ValueError("a weapon match names a type or a weapon")
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


class Gates(BaseModel):
    """The gates an effect reads, all of which hold together."""

    model_config = _STRICT

    with_: WeaponMatch | None = Field(default=None, alias="with")
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
    """What fires an effect.

    The trigger is ``step`` and ``by``. It may also read the ``natural`` face
    its die shows, the outcome it ``is``, the score it ``needed`` or the
    equipment its option ``holds``. The gates must hold as well.
    """

    step: Step | None = None
    by: Role | None = None
    natural: StrictInt | None = Field(default=None, ge=1, le=6)
    is_: Value | None = Field(default=None, alias="is")
    needed: Comparison | None = None
    holds: Annotated[tuple[Slug, ...], Field(min_length=1)] | None = None

    @model_validator(mode="after")
    def _triggers_or_gates(self) -> Self:
        if (self.step is None) != (self.by is None):
            raise ValueError("a trigger names its step and who acts there")
        if self.step is None:
            read = (self.natural, self.is_, self.needed, self.holds)
            if any(each is not None for each in read):
                raise ValueError("natural, is, needed and holds read a trigger's step")
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
    whose block runs it, as a Stand & Shoot volley runs inside stand-and-shoot.
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
            if isinstance(block, Step) and (
                block not in BLOCKS or self.step not in BLOCKS[block].steps
            ):
                raise ValueError(f"{name}: {block} runs no {self.step}")
        if self.in_ is not None and self.in_ == self.not_in:
            raise ValueError(f"in and not_in both name {self.in_}")
        if not self.sequences:
            raise ValueError(f"not_in: {self.step} is printed in no other sequence")
        return self

    @property
    def sequences(self) -> tuple[StepSequence, ...]:
        """The sequences the address can land in."""
        narrowed = BLOCKS[self.in_].sequence if isinstance(self.in_, Step) else self.in_
        return tuple(
            sequence
            for sequence in self.step.sequences
            if narrowed in (None, sequence)
            and not (isinstance(self.not_in, StepSequence) and sequence == self.not_in)
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
            and not self._apart(other)
            and not other._apart(self)
        )

    def mirrored(self) -> "Address":
        """The address as the enemy of the bearer names it.

        Returns:
            The address with its role swapped.
        """
        return self.model_copy(update={"by": _OTHER[self.by]})

    def _apart(self, other: "Address") -> bool:
        excluded = other.in_ is not None and type(other.in_) is type(self.not_in)
        blocks = isinstance(self.in_, Step) and isinstance(other.in_, Step)
        return (excluded and other.in_ == self.not_in) or (blocks and self.in_ != other.in_)

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
    maximum: StrictInt | None = None
    minimum: StrictInt | None = None

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
    times: StrictInt = Field(ge=1)


_ATTRIBUTES = {Operation.SET: "set_"}

_CHOSEN = frozenset({StepKind.ROLL, StepKind.DECISION})

_SLOTS = frozenset({Step.IMPACT_HITS, Step.STOMP_ATTACKS})

Options = Annotated[tuple[Slug, ...], Field(min_length=1)]


class Effect(BaseModel):
    """One printed effect.

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
    to: Role | WeaponMatch | None = None
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
    def amounts(self) -> tuple[Amount, ...]:
        """Every amount the operation reads."""
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
        return "X" in self.amounts

    @property
    def fact_gates(self) -> tuple[FactGate, ...]:
        """Every fact the gates compare."""
        return tuple(gate for gates in self._gates for gate in gates.facts)

    @property
    def fact_refs(self) -> tuple[FactRef, ...]:
        """Every fact read as a value."""
        values = [*self.amounts, *(gate.compared[1] for gate in self.fact_gates)]
        return tuple(value for value in values if isinstance(value, FactRef))

    @property
    def facts(self) -> frozenset[str]:
        """Every fact the effect reads, by name."""
        named = {gate.fact for gate in self.fact_gates}
        return frozenset(named | {ref.fact for ref in self.fact_refs})

    @property
    def rules(self) -> frozenset[str]:
        """Every rule the effect names."""
        foes = [gates.foe for gates in self._gates if gates.foe is not None]
        named = {rule for foe in foes for rule in foe.has or ()}
        if self.grants is not None:
            named.add(self.grants.rule)
        if self.cancels is not None and self.cancels.rule is not None:
            named.add(self.cancels.rule)
        return frozenset(named)

    @property
    def weapons(self) -> frozenset[str]:
        """Every weapon the effect's gates or its grant's target name."""
        named = [gates.with_.weapon for gates in self._gates if gates.with_ is not None]
        if isinstance(self.to, WeaponMatch):
            named.append(self.to.weapon)
        return frozenset(weapon for weapon in named if weapon is not None)

    @property
    def held(self) -> frozenset[str]:
        """Every piece of equipment the trigger's option holds."""
        return frozenset(() if self.when is None or self.when.holds is None else self.when.holds)

    @property
    def armour(self) -> frozenset[str]:
        """Every piece of armour the effect's gates or its bar name."""
        named = {gates.worn.armour for gates in self._gates if gates.worn is not None}
        return frozenset(named if self.bar is None else {*named, self.bar})

    def mirrored(self) -> "Effect":
        """The effect as the enemy of the bearer reads it.

        Returns:
            The effect with the roles of its landing and its ``of`` swapped.
        """
        at = None if self.at is None else self.at.mirrored()
        of = None if self.of is None else _OTHER[self.of]
        return self.model_copy(update={"at": at, "of": of})

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
        if self.grants is not None and self.to is None:
            raise ValueError("a grant names who receives it under to")
        if self.grants is not None and self.at is not None:
            raise ValueError("a grant has no landing of its own")
        if self.grants is None and self.at is None:
            raise ValueError("an effect lands at an address")
        if self.grants is None and self.to is not None:
            raise ValueError("to names who receives a grant")
        return self

    @model_validator(mode="after")
    def _owns_a_characteristic(self) -> Self:
        changes_one = any(isinstance(key, Characteristic) for key in self.keys)
        if changes_one and self.of is None:
            raise ValueError("of names whose characteristic changes")
        if self.of is not None and not changes_one:
            raise ValueError("of belongs to a changed characteristic")
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
    def _fits_its_step(self) -> Self:
        if self.at is None:
            return self
        step = self.at.step
        if self.deny and step.kind is not StepKind.ROLL:
            raise ValueError(f"deny takes away a roll; {step} is a {step.kind}")
        if (self.force is not None or self.substitute is not None) and step.kind not in _CHOSEN:
            raise ValueError(
                f"{self.operation} settles a roll or a decision; {step} is a {step.kind}"
            )
        if self.reroll is not None and not step.rolls:
            raise ValueError(f"reroll needs a die; {step} rolls none")
        if (self.hits is not None or self.fill) and step not in _SLOTS:
            raise ValueError(f"{self.operation} fills a slot of automatic hits; {step} is no slot")
        return self


_BEST = frozenset({Quantity.WARD_SAVE})


def conflicts(rules: Mapping[str, Sequence[Effect]]) -> list[str]:
    """Every pair of rules that clash at one address.

    Two such rules conflict unless either cancels the other there. Each pair is
    compared on one model and on two models facing each other. A Ward save is
    no conflict: a model with more than one uses the best
    (the-shooting-phase/more-than-one-save).

    Returns:
        One message per conflict, naming both rules and the address.
    """
    found = []
    for (first, ours), (second, theirs) in combinations(sorted(rules.items()), 2):
        facing = tuple(effect.mirrored() for effect in theirs)
        for named, others in ((second, theirs), (f"the enemy's {second}", facing)):
            for mine in ours:
                for other in others:
                    if mine.at is None or other.at is None or not mine.at.overlaps(other.at):
                        continue
                    clash = _clash(mine, other)
                    if clash is None or _cancelled(first, mine, ours, second, other, others):
                        continue
                    found.append(f"{first} and {named} {clash} at {mine.at}, and neither cancels")
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
