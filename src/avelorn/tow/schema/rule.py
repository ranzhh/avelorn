"""Rule models for Warhammer: The Old World.

A rule entry carries the printed rule verbatim (name, flavour line, and body
paragraphs as displayed on the page) and, optionally, its hand-authored
``effects`` as the graph reads them (:class:`~avelorn.tow.schema.effect.Effect`).
Effects sit beside the imported text so the structured form can be diffed
against what the rulebook says; a rule without effects is text the engine
holds but does not apply. A rule whose name prints an X declares its
``parameter``, which every reference binds.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from avelorn.tow.schema.effect import Effect, Operation
from avelorn.tow.schema.reference import RuleRef, Slug
from avelorn.tow.schema.unit import ProfileRole

_TEMPLATE = re.compile(r"^(?P<base>.+) \((?P<before>[^()X]*)X(?P<after>[^()X]*)\)$")
_BRACKETED = re.compile(r"^(?P<base>.+) \((?P<inner>[^()]+)\)$")


def printed_base(printed: str) -> str:
    """A printed rule name less its bracket: "Armour Bane (1)" is "Armour Bane".

    Returns:
        The name before the bracket, or the whole name when it prints none.
    """
    bracket = _BRACKETED.match(printed)
    return printed if bracket is None else bracket["base"]


def prints_x(name: str) -> bool:
    """Whether a rule's name prints an X in its bracket: "Regeneration (X+)" does.

    Returns:
        True when the name is a display template for an X.
    """
    return _TEMPLATE.match(name) is not None


_DICE_QUANTITY = re.compile(r"^D(?P<sides>[36])(?:\+(?P<plus>\d+))?$")


class DiceQuantity(BaseModel):
    """A printed quantity decided by a dice roll: "D6", "D3", "D3+1".

    The dice form of a rule's bracketed parameter — "Often, this is
    determined by the roll of a dice" (Stomp Attacks, Impact Hits). One
    die plus a flat addend covers every printed instance; a wider form
    (2D6, say) joins when a rule prints one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sides: Literal[3, 6]
    plus: int = Field(default=0, ge=0)

    @classmethod
    def parse(cls, printed: str) -> "DiceQuantity | None":
        """Read a printed dice quantity off its text.

        Returns:
            The parsed quantity, or None when the text is not one.
        """
        match = _DICE_QUANTITY.match(printed)
        if match is None:
            return None
        sides: Literal[3, 6] = 3 if match.group("sides") == "3" else 6
        return cls(sides=sides, plus=int(match.group("plus") or 0))

    def __str__(self) -> str:
        """The quantity as printed.

        Returns:
            The text :meth:`parse` reads.
        """
        return f"D{self.sides}" + (f"+{self.plus}" if self.plus else "")


class AmountParameter(BaseModel):
    """An X that is a number, or a dice roll where ``dice`` allows one.

    ``min`` and ``max`` bound a number. Two sources of one rule sum their X
    (``combine``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["amount"]
    dice: bool = False
    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)
    combine: Literal["sum"] = "sum"

    @property
    def expected(self) -> str:
        """What an X must be, in words, for an error message."""
        bounds = "".join(
            (
                f" from {self.min}" if self.min is not None else "",
                f" to {self.max}" if self.max is not None else "",
            )
        )
        dice = " or a dice roll (D3, D6, D3+1)" if self.dice else ""
        return f"an amount: a whole number{bounds}{dice}"

    def value(self, x: int | str) -> "int | DiceQuantity":
        """The amount an X stands for.

        Returns:
            The number, or the dice quantity.

        Raises:
            ValueError: X is not what this parameter declares.
        """
        if isinstance(x, int):
            if (self.min is not None and x < self.min) or (self.max is not None and x > self.max):
                raise ValueError(f"X {x!r} is not {self.expected}")
            return x
        dice = DiceQuantity.parse(x) if self.dice else None
        if dice is None:
            raise ValueError(f"X {x!r} is not {self.expected}")
        return dice

    def parse(self, printed: str) -> int | str:
        """Read an X off the text a bracket prints.

        Returns:
            The X a reference carries.
        """
        x: int | str = int(printed) if printed.isdigit() else printed
        self.value(x)
        return x

    def printed(self, x: int | str) -> str:
        return str(x)

    def combined(self, xs: Sequence[int | str]) -> int | str:
        """The X that several sources of the rule make together.

        Returns:
            The one X, or the sum of the numbers.

        Raises:
            ValueError: a dice roll is one of two or more.
        """
        numbers = [x for x in xs if isinstance(x, int)]
        if len(xs) == 1:
            return xs[0]
        if len(numbers) < len(xs):
            raise ValueError(f"X {list(xs)!r} sums a dice roll, which only one source may give")
        return sum(numbers)

    @model_validator(mode="after")
    def _bounds_in_order(self) -> "AmountParameter":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"min {self.min} is above max {self.max}")
        return self


class SelectorValue(BaseModel):
    """One value a selector X may take, and how the bracket prints it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    printed: str = Field(min_length=1)


class SelectorParameter(BaseModel):
    """An X that names one of a closed set, keyed by slug: Hatred's hated enemies."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["selector"]
    values: Annotated[dict[str, SelectorValue], Field(min_length=1)]
    combine: Literal["union"] = "union"

    @property
    def expected(self) -> str:
        """What an X must be, in words, for an error message."""
        return f"a selector: one of {', '.join(sorted(self.values))}"

    def value(self, x: int | str) -> str:
        """The selector value an X names.

        Returns:
            The value's key.

        Raises:
            ValueError: X names no declared value.
        """
        if not isinstance(x, str) or x not in self.values:
            raise ValueError(f"X {x!r} is not {self.expected}")
        return x

    def parse(self, printed: str) -> str:
        """The key of the value a bracket prints.

        Returns:
            The X a reference carries.

        Raises:
            ValueError: no declared value prints as ``printed``.
        """
        for key, value in self.values.items():
            if value.printed == printed:
                return key
        raise ValueError(f"{printed!r} is not {self.expected}")

    def printed(self, x: int | str) -> str:
        """The text a bracket prints for an X.

        Returns:
            The value as printed.
        """
        return self.values[self.value(x)].printed

    def combined(self, xs: Sequence[int | str]) -> int | str:
        """The union of the values several sources of the rule give.

        Returns:
            The one value they all give.

        Raises:
            ValueError: they give two values, a union an X cannot hold yet.
        """
        if len(set(xs)) > 1:
            raise ValueError(
                f"X {sorted(map(str, set(xs)))} unite two values, which one X cannot hold yet"
            )
        return xs[0]


class PrintedParameter(BaseModel):
    """An X kept as the text its bracket prints: a text-only stub's, read by no effect."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["printed"]

    @property
    def expected(self) -> str:
        """What an X must be, in words, for an error message."""
        return "the text its bracket prints"

    def value(self, x: int | str) -> str:
        """The text an X stands for.

        Returns:
            The X, as text.

        Raises:
            ValueError: X is empty.
        """
        if x == "":
            raise ValueError(f"X {x!r} is not {self.expected}")
        return str(x)

    def parse(self, printed: str) -> int | str:
        """Read an X off the text a bracket prints.

        Returns:
            The X a reference carries: a number where the text is one.
        """
        return int(printed) if printed.isdigit() else printed

    def printed(self, x: int | str) -> str:
        return self.value(x)

    def combined(self, xs: Sequence[int | str]) -> int | str:
        """The X that several sources of the rule make together.

        Returns:
            The one X they all give.
        """
        return _one(xs)


def _one(xs: Sequence[int | str]) -> int | str:
    distinct = set(xs)
    if len(distinct) != 1:
        raise ValueError(f"X {sorted(map(str, distinct))} differ between sources")
    return xs[0]


Parameter = Annotated[
    AmountParameter | SelectorParameter | PrintedParameter, Field(discriminator="kind")
]


class Rule(BaseModel):
    """A rules-page entry (special rule or core rule), text verbatim, with its effects.

    ``may`` marks a rule its player may decline. ``not_on`` names the profile
    rows the rule stops at, as "but not its mount" does. ``needs`` names the
    mechanics a printed clause needs that the engine lacks, each a ledger subject.
    ``notes`` are the author's words on the scope modelled and what is left out.
    """

    model_config = ConfigDict(extra="forbid")

    id: str  # stable slug, e.g. "armour-bane"
    name: str  # printed name, e.g. "Armour Bane (X)"
    parameter: Parameter | None = None
    page: int | None = None  # rulebook page reference
    category: str | None = None  # site rule category, e.g. "Special Rules"
    flavour: str | None = None  # italic flavour line, if any
    paragraphs: list[str] = Field(min_length=1)  # rule text, as displayed
    may: bool = False
    not_on: tuple[ProfileRole, ...] = ()
    needs: tuple[Slug, ...] = ()
    effects: tuple[Effect, ...] = ()
    notes: str | None = None

    @model_validator(mode="after")
    def _a_parameter_prints_in_the_name(self) -> "Rule":
        if self.parameter is not None and not prints_x(self.name):
            raise ValueError(
                f"{self.name!r} declares a parameter, but its name prints no X to show it in"
            )
        if self.parameter is None and prints_x(self.name):
            raise ValueError(f"{self.name!r} prints an X, but the rule declares no parameter")
        return self

    @model_validator(mode="after")
    def _effects_read_a_declared_parameter(self) -> "Rule":
        reads = any(effect.reads_x for effect in self.effects)
        if reads and (self.parameter is None or self.parameter.kind != "amount"):
            raise ValueError(f"an effect of {self.name!r} reads an X the rule does not declare")
        return self

    def display(self, x: int | str | None) -> str:
        """The rule's name as a reference with this X prints it.

        Returns:
            The name, with X substituted into its bracket.

        Raises:
            ValueError: X is missing, extra, or not what the rule declares.
        """
        if self.parameter is None:
            if x is not None:
                raise ValueError(f"X {x!r} given, but {self.id} declares no X")
            return self.name
        if x is None:
            raise ValueError(f"X missing; {self.id} expects {self.parameter.expected}")
        template = _TEMPLATE.match(self.name)
        if template is None:
            raise ValueError(f"{self.name!r} prints no X to show {x!r} in")
        printed = self.parameter.printed(x)
        return f"{template['base']} ({template['before']}{printed}{template['after']})"

    @property
    def base(self) -> str:
        """The name less the bracket its X prints in, or the whole name."""
        template = _TEMPLATE.match(self.name)
        return self.name if template is None else template["base"]

    def read(self, printed: str) -> RuleRef:
        """The reference a printed name makes to this rule.

        Returns:
            The slug, with the X the bracket prints when the rule declares one.

        Raises:
            ValueError: the bracket is missing, extra, signed against the name,
                or not the X the rule declares.
        """
        if printed == self.name and self.parameter is None:
            return RuleRef(rule=self.id)
        template = _TEMPLATE.match(self.name)
        if self.parameter is None or template is None:
            raise ValueError(f"{printed!r} prints an X, but {self.id} declares none")
        bracket = _BRACKETED.match(printed)
        if bracket is None:
            expected = self.parameter.expected
            raise ValueError(f"{printed!r} prints no X; {self.id} expects {expected}")
        before, after, inner = template["before"], template["after"], bracket["inner"]
        signed = inner.startswith(before) and inner.endswith(after)
        if not signed or len(inner) <= len(before) + len(after):
            raise ValueError(f"{printed!r} does not print X as {self.name!r} does")
        x = self.parameter.parse(inner[len(before) : len(inner) - len(after)])
        return RuleRef(rule=self.id, X=x)

    def bound(self, x: int | str | None) -> "Rule":
        """The rule as a reference with this X carries it.

        Returns:
            The entry itself when it declares no parameter; otherwise a copy
            named as printed.

        Raises:
            ValueError: X is missing, extra, or not what the rule declares, or
                a dice roll an effect would add.
        """
        name = self.display(x)
        if self.parameter is None or x is None:
            return self
        value = self.parameter.value(x)
        if isinstance(value, DiceQuantity) and any(map(_adds_x, self.effects)):
            raise ValueError(
                f"X {x!r} is a dice roll, which binds only into a count (hits, multiplies), "
                f"never into an amount an effect of {self.id} adds"
            )
        return self.model_copy(update={"name": name})


def bind(reference: RuleRef, rules: Mapping[str, Rule]) -> Rule:
    """The rule a reference names, bound to its X.

    Returns:
        The bound rule (:meth:`Rule.bound`).

    Raises:
        ValueError: no entry carries the slug, or the X does not bind.
    """
    rule = rules.get(reference.rule)
    if rule is None:
        raise ValueError(f"no rule entry {reference.rule!r}")
    return rule.bound(reference.x)


def _adds_x(effect: Effect) -> bool:
    return effect.reads_x and effect.operation not in {Operation.HITS, Operation.MULTIPLY}
