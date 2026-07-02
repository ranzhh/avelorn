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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from avelorn.tow.schema.stage import Stage


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


# Becomes a discriminated union (Field(discriminator="kind")) when the
# second effect kind joins; the data format already carries the
# discriminator, so authored files never change shape.
RuleEffect = ArmourPiercingEffect


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
