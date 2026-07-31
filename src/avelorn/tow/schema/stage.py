"""The attack sequence's stages: the registry of named game moments.

Stage names are taken verbatim from the printed shooting-phase sequence
(tow.whfb.app/the-shooting-phase): Roll to Hit, Roll to Wound, Make
Armour Saves, Ward Saves, Make Panic Tests — the naming asymmetry is the
rulebook's own ("Ward Saves" is a universal-rule section, never phrased
imperatively).

This registry is the vocabulary that rule data references and the
combat engine hooks; it lives in the schema layer, like the other
closed rulebook vocabularies (troop types), so that referencing an
unknown stage fails at data load. It is append-only: a name joins when
a seam exists in code or imported rule text demands it, and may precede
the engine implementing it — the compiler treats a named-but-unhooked
stage as not yet modelled, never as an error.

Each member declares its printed row — the name, whose dice the stage
rolls, and what is rolled — so the enum mirrors the rulebook's sequence
table the way the troop-type enum mirrors its table. Both facts are the
rulebook's own constants, never authored in rule data: the sequence
fixes that the attacker rolls To Hit and To Wound while the target rolls
its saves and panic tests, and that a panic test is one 2D6 roll for the
whole unit where every other stage rolls one D6 per attack (so only
those stages can show a "natural" face).
"""

from enum import StrEnum


class Side(StrEnum):
    """A party of one attack, as the rulebook names the two.

    The attack sequence has exactly two seats — the attacker making the
    attack and the target suffering it — and stages and quantities are
    owned by one or the other. The vocabulary matches the ``target_of``
    gate: the rulebook speaks of "the attacking unit" and "the target".
    """

    ATTACKER = "attacker"
    TARGET = "target"

    @property
    def other(self) -> "Side":
        """The opposite seat of the same attack."""
        return Side.TARGET if self is Side.ATTACKER else Side.ATTACKER


class Dice(StrEnum):
    """What a stage rolls, as the sequence prints it.

    ``D6_PER_ATTACK`` is one die per attack — the rolls that can show a
    natural face, and the only dice a re-roll grant or an ``on_natural``
    trigger can name. ``TWO_D6_PER_UNIT`` is a single 2D6 test for the
    whole unit (Make Panic Tests), where no single natural face exists.
    """

    D6_PER_ATTACK = "d6-per-attack"
    TWO_D6_PER_UNIT = "2d6-per-unit"


class Stage(StrEnum):
    """The attack sequence's stages, one row per printed step.

    Each member is a row of the printed sequence: its name (verbatim),
    ``rolled_by`` (whose dice the stage rolls — the attacker's To Hit and
    To Wound, the target's saves and panic tests), and ``dice`` (what is
    rolled there). Declaration order is the printed order — the engine's
    "can this die still shape that roll" reads it directly.
    """

    _value_: str
    rolled_by: Side
    dice: Dice

    def __new__(cls, value: str, rolled_by: Side, dice: Dice) -> "Stage":
        """Build one row: the string is the member's value, the facts its attributes."""
        member = str.__new__(cls, value)
        member._value_ = value
        member.rolled_by = rolled_by
        member.dice = dice
        return member

    ROLL_TO_HIT = "roll-to-hit", Side.ATTACKER, Dice.D6_PER_ATTACK
    ROLL_TO_WOUND = "roll-to-wound", Side.ATTACKER, Dice.D6_PER_ATTACK
    MAKE_ARMOUR_SAVES = "make-armour-saves", Side.TARGET, Dice.D6_PER_ATTACK
    WARD_SAVES = "ward-saves", Side.TARGET, Dice.D6_PER_ATTACK
    MAKE_PANIC_TESTS = "make-panic-tests", Side.TARGET, Dice.TWO_D6_PER_UNIT
