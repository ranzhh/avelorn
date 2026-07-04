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
"""

from enum import StrEnum


class Stage(StrEnum):
    """The attack sequence's stages, named as the rulebook prints them."""

    ROLL_TO_HIT = "roll-to-hit"
    ROLL_TO_WOUND = "roll-to-wound"
    MAKE_ARMOUR_SAVES = "make-armour-saves"
    WARD_SAVES = "ward-saves"
    MAKE_PANIC_TESTS = "make-panic-tests"
