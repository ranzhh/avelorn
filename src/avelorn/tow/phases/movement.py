"""The Movement phase: charges are declared, reacted to, and moved.

A charge is a Movement-phase event, and only that: :func:`charge` rolls the
charger's charge range and returns the :class:`Engagement` it forms when it
reaches (the two units locked in combat). The target answers with a reaction
on that engagement (:meth:`Engagement.react`, the-movement-phase/charge-reactions) —
:class:`StandAndShoot` looses the one "free" volley as the chargers close
(:func:`~avelorn.tow.volley.stand_and_shoot`), :class:`Hold` braces, Flee is
not modelled yet. The melee the charge sets up is **not** fought here: that is
the Combat phase (:meth:`~avelorn.tow.phases.combat.CombatPhase.fight`), which
takes the engagement and enters the chargers thinned by any Stand & Shoot.
"""

from dataclasses import dataclass, replace
from typing import assert_never

from avelorn.core.errors import UnmodelledRuleError
from avelorn.core.game import Phase
from avelorn.tow import volley
from avelorn.tow.charge import ChargeRoll, roll_charge
from avelorn.tow.contingent import Charge, Contingent
from avelorn.tow.programs import Loaded
from avelorn.tow.volley import Volley


@dataclass(frozen=True)
class Hold:
    """The Hold charge reaction: brace and await the charge."""


@dataclass(frozen=True)
class StandAndShoot:
    """The Stand & Shoot charge reaction: the target fires as the chargers close."""

    # The printed name of the missile weapon to fire, or None to fire the
    # reacting unit's sole missile weapon. Named because the reaction fires a
    # different weapon from the one the unit swings in the ensuing melee, so
    # the weapon it holds for the fight does not decide the volley; None is
    # the shortcut when there is only one missile weapon it could be.
    weapon: str | None = None


@dataclass(frozen=True)
class Flee:
    """The Flee charge reaction; declared in the vocabulary, not modelled yet."""


# The printed vocabulary, exhaustive: "There are three charge reactions
# available to the inactive player: Hold, Stand & Shoot and Flee"
# (the-movement-phase/charge-reactions, p.120).
ChargeReaction = Hold | StandAndShoot | Flee

# The default declaration: a target that declares nothing holds.
HOLD = Hold()


@dataclass
class Engagement:
    """Units locked in combat — the live, mutable combat state.

    Not loaded data or a resolved outcome (those stay frozen) but ongoing game
    state, so it is mutable. An engagement is strictly two units — ``a`` and
    ``b`` — in base contact: the atom the Combat phase resolves. (A combat of
    more than two units, one unit fighting several, is a collection of
    engagements — a graph of who is touching whom — resolved by fighting each
    pairing and combining the results; that is a later ``Combat`` type, once
    the engine fights more than 1v1.)

    An engagement is set up by a charge — the only opening modelled today;
    units already in base contact are the "or something else" for later. When a
    charge forms it, ``a`` is the charger (carrying its
    :class:`~avelorn.tow.contingent.Charge` via
    :meth:`~avelorn.tow.contingent.Contingent.charging`), ``b`` the target it
    struck, ``program`` the Stand & Shoot program a reaction fires on,
    ``rolled`` the charge's Charge roll, and ``reaction`` the target's Stand &
    Shoot volley once declared, thinning ``a``. The engagement is the combat
    the charge forms when it reaches, so a round fought on it is fought given
    that it reached. ``first_round`` is true for the round a charge sets up
    this turn — when the charge Initiative bonus and the first-round rules apply;
    :meth:`end_turn` flips it false so the combat's later rounds (next turn on)
    fight as subsequent rounds. The Combat phase fights the engagement
    (:meth:`~avelorn.tow.phases.combat.CombatPhase.fight`).
    """

    a: Contingent
    b: Contingent
    program: Loaded
    rolled: ChargeRoll
    # True for the round a charge sets up this turn (the combat's first round);
    # end_turn() flips it false so later rounds are not the first.
    first_round: bool = False
    reaction: Volley | None = None

    def react(self, reaction: ChargeReaction = HOLD) -> Volley | None:
        """Answer the charge — the inactive player's declared reaction.

        One of the printed three: :class:`Hold` (brace, no volley),
        :class:`StandAndShoot` (``b`` looses one volley at the closing charger
        ``a`` -- the "free" shot; its weapon is named, or its sole missile
        weapon by default), or :class:`Flee` (a loud error until modelled).
        Records the volley on the engagement so the Combat phase can enter the
        charger already thinned.

        Returns:
            The reaction volley, or None for a Hold.

        Raises:
            UnmodelledRuleError: the declared reaction is Flee.
        """
        match reaction:
            case StandAndShoot(weapon=name):
                shooter = (
                    self.b.wielding(name) if name is not None else replace(self.b, weapon=None)
                )
                self.reaction = volley.stand_and_shoot(self.program, shooter, self.a)
            case Flee():
                raise UnmodelledRuleError("the Flee charge reaction is not modelled yet")
            case Hold():
                self.reaction = None
            case unanswered:
                # A reaction joining the vocabulary must be answered here —
                # a charge whose target silently did nothing is the wrong game.
                assert_never(unanswered)
        return self.reaction

    def end_turn(self) -> None:
        """Age the engagement out of its first round as the turn ends.

        A combat fought this turn is no longer in its first round next turn,
        so its charge Initiative bonus and first-round rules lapse. The turn
        calls this on each open engagement as it ends.
        """
        self.first_round = False


def charge(
    charger: Contingent,
    target: Contingent,
    move: Charge,
    *,
    program: Loaded,
    charging: Loaded,
) -> Engagement:
    """Declare ``charger``'s charge on ``target`` and roll its range on ``charging``.

    The engagement is the two units locked in combat once the charge reaches
    (its movement becomes the charge), with the chance it does. This resolves
    **no melee** — that is the Combat phase
    (:meth:`~avelorn.tow.phases.combat.CombatPhase.fight`). The target answers
    on the returned :class:`Engagement` (:meth:`Engagement.react`); a Stand &
    Shoot volley there fires on ``program``.

    Returns:
        The engagement the charge forms, awaiting its reaction and its fight.
    """
    return Engagement(
        a=charger.charging(move),
        b=target,
        program=program,
        rolled=roll_charge(charging, charger, target, move),
        first_round=True,
    )


@dataclass(frozen=True)
class MovementPhase(Phase):
    """The Movement phase: charges are declared, reacted to, and moved here.

    ``program`` is the Stand & Shoot program, loaded with the corpus rules; a
    Stand & Shoot reaction fires on it. ``charging`` is the charge program, on
    which each charge rolls its range.
    """

    program: Loaded
    charging: Loaded

    def charge(self, charger: Contingent, target: Contingent, move: Charge) -> Engagement:
        """Declare a charge and roll its range, forming the engagement it makes when it reaches.

        The target's reaction is declared on the returned engagement
        (:meth:`Engagement.react`); the Combat phase fights it.

        Returns:
            The engagement the charge forms.
        """
        return charge(charger, target, move, program=self.program, charging=self.charging)
