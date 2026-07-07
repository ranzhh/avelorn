"""Rule models for Warhammer: The Old World.

A rule entry carries the printed rule verbatim — name, flavour line,
and body paragraphs as displayed on the page — plus, optionally, its
executable ``effects``. Effects are hand-authored alongside the
imported text precisely so the structured form can be diffed against
what the rulebook actually says; a rule without effects is data the
engine recognises but cannot yet apply.

Most effects are **modifiers**: a change to one of the attack's
printed quantities, gated by a shared trigger vocabulary. The ``kind``
names the quantity in the rulebook's own modifier language ("To Hit
modifier", "the Armour Piercing characteristic ... is improved") and
implies where in the attack sequence the change lands; the triggers —
engagement facts (``when``) and a natural face on one stage's die
(``on_natural``) — say when it fires. What changes and when it fires
are separate halves of the sentence, and the YAML mirrors that split.
Other kinds are payloads consumed by their own seams (a re-roll
grant). Kinds are named after mechanics the rulebook itself names,
never after the rules that use them: a kind must serve any rule
sharing the mechanic, or the vocabulary degrades into per-rule scripts
in YAML dress — a rule too bespoke for any general kind belongs in a
code handler, as itself. Anything a rule needs that no kind expresses
stays unmodelled (and is reported by the engine) rather than
approximated.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from avelorn.tow.schema.psychology import PanicCause
from avelorn.tow.schema.stage import ATTACK_ROLLS, Stage

# The printed convention for a parameterised rule: the name is filed
# under an "(X)" placeholder ("Armour Bane (X)"), and effects reference
# the parameter as the literal "X" ("the amount shown in brackets after
# the name of this special rule").
PARAMETER_SUFFIX = " (X)"


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


# The quantities a modifier can change, in the rulebook's own modifier
# vocabulary. Each member implies the stage its change lands on — the
# compiler owns that mapping, exhaustively.
ModifierKind = Literal["to-hit", "armour-piercing"]


class NaturalRoll(BaseModel):
    """A natural face shown by one of the attack sequence's dice.

    The *event* half of the trigger vocabulary — "rolls a natural 6
    when making a roll To Wound". Where ``when`` gates on engagement
    state, known once before any die is cast (and possibly unknown),
    an event is decided branch by branch during resolution and is never
    unknown. ``roll`` must name one of the attack sequence's rolls —
    the closed :data:`~avelorn.tow.schema.stage.ATTACK_ROLLS`
    vocabulary, checked at data load.
    """

    model_config = ConfigDict(extra="forbid")

    face: int = Field(ge=1, le=6)
    roll: Stage

    @field_validator("roll")
    @classmethod
    def _a_die_is_rolled_there(cls, roll: Stage) -> Stage:
        if roll not in ATTACK_ROLLS:
            raise ValueError(f"{roll} is not an attack roll; no natural face is shown there")
        return roll


# The "natural" key in a ``when`` mapping: the one event trigger,
# beside the state conditions. A drift-guard test keeps it from ever
# colliding with a Condition member.
NATURAL = "natural"

# A trigger fact: a state condition's required answer, or the natural
# roll the event key names.
TriggerFact = bool | NaturalRoll


class ModifierEffect(BaseModel):
    """One printed conditional modifier, shaped as the sentence prints it.

    "*If* a model rolls a natural 6 when making a roll To Wound, the
    Armour Piercing of its weapon is improved by X" — ``when`` holds
    the if, ``then`` holds the consequence. ``when`` is one flat
    conjunction: state conditions by :class:`Condition` member (facts
    of the engagement, known once before any die is cast; an
    unanswerable one leaves the whole rule unfactored and reported,
    one answered False is honoured by not applying) and at most one
    ``natural`` event (:class:`NaturalRoll` — a face shown by an attack
    die, decided branch by branch, never unknown). Without a ``when``
    the modifier applies to every attack. Deliberately not a language:
    no ``else``, no nesting — an effect is one flat ``when`` and one
    ``then``, and a rule needing more belongs in a code handler.

    ``then`` maps each modified quantity to its printed amount, in the
    quantity's own printed sign convention: To Hit penalties negative
    ("-1 To Hit modifier" is ``to-hit: -1``), Armour Piercing
    improvements positive ("improved by 1" is ``armour-piercing: 1``).
    The literal ``"X"`` means the rule's bracketed parameter ("the
    amount shown in brackets after the name of this special rule").
    Where a change lands in the attack sequence follows from its
    quantity, so no stage is spelled out.
    """

    model_config = ConfigDict(extra="forbid")

    when: Annotated[dict[Condition | Literal["natural"], TriggerFact], Field(min_length=1)] | (
        None
    ) = None
    then: Annotated[dict[ModifierKind, int | Literal["X"]], Field(min_length=1)]

    @model_validator(mode="after")
    def _facts_match_their_keys(self) -> "ModifierEffect":
        # One flat mapping, two kinds of key: a state condition requires
        # true/false, the event key requires the natural roll.
        for key, fact in (self.when or {}).items():
            if key == NATURAL and not isinstance(fact, NaturalRoll):
                raise ValueError("'natural' names a die's face: {face, roll}")
            if key != NATURAL and not isinstance(fact, bool):
                raise ValueError(f"condition {key!r} requires true or false")
        return self

    @property
    def natural(self) -> NaturalRoll | None:
        """The event trigger, if the when names one.

        Returns:
            The natural roll, or None for a state-only when.
        """
        fact = (self.when or {}).get(NATURAL)
        return fact if isinstance(fact, NaturalRoll) else None

    @property
    def conditions(self) -> dict[Condition, bool]:
        """The state triggers: the engagement facts the when asks.

        Returns:
            The required answer per asked condition.
        """
        return {
            key: fact
            for key, fact in (self.when or {}).items()
            if isinstance(key, Condition) and isinstance(fact, bool)
        }


class RerollEffect(BaseModel):
    """Re-roll a failed test, under the printed re-roll rules.

    A re-roll happens at most once whatever its source ("no single dice
    can be re-rolled more than once, regardless of the source"), and a
    multi-dice roll re-rolls all its dice. Unlike a modifier, the
    ``stage`` here is the payload — *which* test is re-rolled — and the
    seam owning that stage consumes the grant directly. ``causes``
    restricts the grant to specific panic causes (Valour of Ages
    re-rolls only heavy casualties and fled through); empty means any
    cause.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["re-roll"]
    stage: Stage
    causes: list[PanicCause] = Field(default_factory=list)


RuleEffect = ModifierEffect | RerollEffect


def references_parameter(effect: RuleEffect) -> bool:
    """Whether any of the effect's values reference the X parameter.

    Introspects the effect's fields, looking inside mappings (a
    ``then``'s amounts), so a new X-bearing field participates
    automatically.

    Returns:
        True if the literal "X" appears as a field or mapping value.
    """
    for name in type(effect).model_fields:
        value = getattr(effect, name)
        if value == "X" or (isinstance(value, Mapping) and "X" in value.values()):
            return True
    return False


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

    @model_validator(mode="after")
    def _parameter_requires_placeholder_name(self) -> "Rule":
        # An effect may reference the bracketed parameter ("X") only if
        # the printed name declares one ("Armour Bane (X)") — checked at
        # load, so an unbindable placeholder is a data error, not a
        # runtime surprise. Introspects the effect's fields, so a new
        # X-bearing kind participates automatically.
        if not self.name.endswith(PARAMETER_SUFFIX):
            for effect in self.effects:
                if references_parameter(effect):
                    raise ValueError(
                        f"an effect of {self.name!r} references the X parameter, "
                        f"but the name does not end in {PARAMETER_SUFFIX!r}"
                    )
        return self
