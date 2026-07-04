"""Rule models for Warhammer: The Old World.

A rule entry carries the printed rule verbatim — name, flavour line,
and body paragraphs as displayed on the page — plus, optionally, its
executable ``effects``. Effects are hand-authored alongside the
imported text precisely so the structured form can be diffed against
what the rulebook actually says; a rule without effects is data the
engine recognises but cannot yet apply.

Every effect is one typed kind, selected by its ``kind`` field, with
the fields that kind requires — the closed vocabulary grows one kind at
a time as the engine learns to honour more. Kinds are named after
mechanics the rulebook itself names (a characteristic, an outcome
class), never after the rules that use them: a kind must serve any rule
sharing the mechanic, or the vocabulary degrades into per-rule scripts
in YAML dress — a rule too bespoke for any general kind belongs in a
code handler, as itself. Anything a rule needs that no kind expresses
stays unmodelled (and is reported by the engine) rather than
approximated.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from avelorn.tow.schema.psychology import PanicCause
from avelorn.tow.schema.stage import Stage


class Condition(StrEnum):
    """The engagement facts an effect can be gated on — the "when" vocabulary.

    The single declaration, like :class:`~avelorn.tow.schema.stage.Stage`
    for game moments: an effect's ``when`` maps members to the value it
    requires, and the engine supplies a fact per member — both checked
    against this enum, so a name outside it fails at data load and a
    member the engine forgets to answer fails its drift guard. It is
    append-only: a member joins when an imported rule's condition needs
    it and the engagement context can carry the fact.
    """

    MOVED = "moved"  # "moved for any reason during this turn"
    AT_LONG_RANGE = "at_long_range"  # "further away than half the weapon's maximum range"


class ArmourPiercingEffect(BaseModel):
    """Improve the weapon's Armour Piercing, as Armour Bane does.

    ``stage`` is the attack-sequence stage the effect hooks, from the
    registry in :mod:`avelorn.tow.schema.stage` — an unknown stage fails
    at data load, while a registry stage the engine does not hook yet
    degrades to "not factored" at compile. ``on_natural`` restricts the
    effect to a natural face on that stage's die ("rolls a natural 6").
    ``amount`` is the improvement; the literal ``"X"`` means the rule's
    bracketed parameter ("the amount shown in brackets after the name
    of this special rule").
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["armour-piercing"]
    stage: Stage
    on_natural: int | None = Field(default=None, ge=1, le=6)
    amount: int | Literal["X"]


class ToHitEffect(BaseModel):
    """Modify the To Hit roll, as the printed To Hit Modifiers do.

    ``amount`` follows the printed sign convention: penalties are
    negative ("-1 To Hit modifier" is ``amount: -1``). ``when`` gates
    the effect on the engagement: required facts by
    :class:`Condition`, conjunctive — every one must match for the
    effect to apply. A fact the context cannot answer (unknown) leaves
    the whole rule unfactored and reported; one answered False simply
    means the rule does not apply (no note — a unit that did not move
    is correctly unpenalised). Without ``when`` the modifier applies to
    every attack.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["to-hit"]
    stage: Stage
    amount: int
    when: Annotated[dict[Condition, bool], Field(min_length=1)] | None = None


class RerollEffect(BaseModel):
    """Re-roll a failed test, under the printed re-roll rules.

    A re-roll happens at most once whatever its source ("no single dice
    can be re-rolled more than once, regardless of the source"), and a
    multi-dice roll re-rolls all its dice. ``causes`` restricts the
    grant to specific panic causes (Valour of Ages re-rolls only heavy
    casualties and fled through); empty means any cause.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["re-roll"]
    stage: Stage
    causes: list[PanicCause] = Field(default_factory=list)


RuleEffect = Annotated[
    ArmourPiercingEffect | ToHitEffect | RerollEffect, Field(discriminator="kind")
]


class Rule(BaseModel):
    """A rules-page entry (special rule or core rule), text verbatim."""

    model_config = ConfigDict(extra="forbid")

    id: str  # stable slug, e.g. "armour-bane"
    name: str  # printed name, e.g. "Armour Bane (X)"
    page: int | None = None  # rulebook page reference
    category: str | None = None  # site rule category, e.g. "Special Rules"
    flavour: str | None = None  # italic flavour line, if any
    paragraphs: list[str] = Field(min_length=1)  # rule text, as displayed
    effects: list[RuleEffect] = Field(default_factory=list)
