"""Morale vocabularies: the printed causes of panic, and Break-test results.

The Psychology of War chapter names exactly four panic causes, each its own
section (tow.whfb.app/the-psychology-of-war): Heavy Casualties, Nearby
Friend Destroyed, Nearby Friend Flees Combat, Fled Through. Effects
that touch panic tests filter on them. The Combat phase's Break test resolves
to one of three printed results (:class:`BreakOutcome`); a rule may fix which
one a lost round produces (Stubborn).
"""

from enum import StrEnum


class PanicCause(StrEnum):
    """Why a panic test was forced, named as the sections are printed."""

    HEAVY_CASUALTIES = "heavy-casualties"
    NEARBY_FRIEND_DESTROYED = "nearby-friend-destroyed"
    NEARBY_FRIEND_FLEES_COMBAT = "nearby-friend-flees-combat"
    FLED_THROUGH = "fled-through"


class Outcome(StrEnum):
    """A result of a decision that a rule may force — the base of every such set.

    Each decision's own results subclass this (a closed set per decision); a
    :class:`~avelorn.tow.schema.rule.ChoiceEffect` forces one, and the concrete
    type is what routes it to the seam that owns that decision. Empty here so
    the generic effect and seam depend only on the base, never on a decision.
    """


class BreakOutcome(Outcome):
    """A Break test's printed result — the closed set a lost round can produce.

    The three outcomes the-combat-phase/break-test names, worst to best for the
    loser's survival: it Breaks (flees, and may be run down), Falls Back in Good
    Order, or Gives Ground.
    """

    GIVES_GROUND = "gives-ground"
    FALLS_BACK = "fall-back-in-good-order"
    BREAKS = "breaks"
