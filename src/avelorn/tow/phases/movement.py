"""The Movement phase: charges are declared, reacted to, and moved.

A charge is a Movement-phase event, and only that: :func:`charge` moves the
charger into contact and returns the :class:`Engagement` it forms (the two
units locked in combat). The target answers with a reaction on that
engagement (:meth:`Engagement.react`, the-movement-phase/charge-reactions) —
:class:`StandAndShoot` looses the one "free" volley as the chargers close
(:func:`stand_and_shoot`, callable on its own), :class:`Hold` braces, Flee is
not modelled yet. The melee the charge sets up is **not** fought here: that is
the Combat phase (:func:`~avelorn.tow.phases.combat.fight`), which takes the
engagement and enters the chargers thinned by any Stand & Shoot casualties.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import assert_never

from avelorn.core.errors import UnmodelledRuleError
from avelorn.core.game import Phase
from avelorn.tow.contingent import Charge, Contingent
from avelorn.tow.phases.shooting import ShootingResult, shoot_unit
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.weapon import Weapon

logger = logging.getLogger(__name__)

# An empty registry as the default: every rule stays unfactored, visibly.
# No rules in force: the volley resolves under weapon and armour alone.
_NONE_IN_PLAY: Mapping[str, Rule] = {}

# Models making a Stand & Shoot reaction suffer -1 To Hit and no Firing at
# Long Range modifier (the-shooting-phase/standing-and-shooting).
_STAND_AND_SHOOT_TO_HIT = -1


def stand_and_shoot(
    shooter: Contingent,
    target: Contingent,
    weapon: Weapon,
    *,
    phase_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
) -> ShootingResult:
    """Resolve a Stand & Shoot charge reaction: ``shooter`` shoots the ``target``.

    The charged unit (``shooter``) looses one volley from ``weapon`` at the
    charging unit (``target``) as it closes, then Holds
    (the-movement-phase/stand-and-shoot). Two printed modifiers set this
    apart from an ordinary volley (the-shooting-phase/standing-and-shooting):
    a **-1 To Hit** for firing at a fast-closing target, and **no Firing at
    Long Range penalty** — the shot lands even beyond the weapon's maximum
    range, at no range modifier. The shooters are standing (they have not
    moved), so Moving and Shooting does not apply either — but Volley Fire
    is forbidden on this reaction, so only the front rank fires. The charging unit
    is **not** required to make a Panic test for these casualties, so no
    morale seam is composed on the result — the survivors simply press home
    the charge.

    Eligibility (line of sight, the gap being no less than the chargers'
    Movement, and the shooters being neither fleeing nor already engaged) is
    the declaration step's concern and assumed here. Casualties cap at the
    charging unit's ``models``.

    Returns:
        The volley's outcome — a distribution of chargers felled before they
        strike.
    """
    logger.debug("stand & shoot: %s fires on charging %s", shooter.unit.name, target.unit.name)
    return shoot_unit(
        shooter,
        target,
        weapon,
        phase_rules=phase_rules,
        hit_modifier=_STAND_AND_SHOOT_TO_HIT,
        force_short_range=True,
        stand_and_shoot=True,
    )


@dataclass(frozen=True)
class Hold:
    """The Hold charge reaction: brace and await the charge."""


@dataclass(frozen=True)
class StandAndShoot:
    """The Stand & Shoot charge reaction: the target fires as the chargers close."""

    weapon: Weapon  # the missile weapon; must be carried by the reacting unit


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
    state, so it is mutable. An engagement is set up by a charge — the only
    opening modelled today; units already in base contact are the "or something
    else" for later — and is fought each Combat phase for as long as the combat
    lasts. It holds the ``charger`` (carrying its
    :class:`~avelorn.tow.contingent.Charge` via
    :meth:`~avelorn.tow.contingent.Contingent.charging`), the ``target`` it
    struck, the charge ``reaction`` once declared, and ``first_round``.

    ``first_round`` is true for the round the charge sets up this turn — when
    the charge Initiative bonus and the first-round rules apply. :meth:`end_turn`
    flips it false, so the combat's later rounds (next turn on) fight as
    subsequent rounds. The Combat phase fights the engagement
    (:func:`~avelorn.tow.phases.combat.fight_engagement`); the reaction's
    casualties thin the chargers as they enter the melee.

    (One pair for now; a real combat can lock two or more units — the
    single-pair case until that is modelled.)
    """

    charger: Contingent
    target: Contingent
    # True for the round a charge sets up this turn (the combat's first round);
    # end_turn() flips it false so later rounds are not the first.
    first_round: bool = False
    # The shooting chapter's rules in force, captured for a Stand & Shoot
    # reaction volley; a bare charge (outside a game) carries none.
    shooting_rules: Mapping[str, Rule] = field(default_factory=dict)
    # The Stand & Shoot outcome once reacted, None while unanswered or on Hold.
    reaction: ShootingResult | None = None

    def react(self, reaction: ChargeReaction = HOLD) -> ShootingResult | None:
        """Answer the charge — the inactive player's declared reaction.

        One of the printed three: :class:`Hold` (brace, no volley),
        :class:`StandAndShoot` (one volley at the closing chargers, under the
        shooting rules in force — the "free" shot), or :class:`Flee` (a loud
        error until modelled). Records the volley on the engagement so the
        Combat phase can enter the chargers already thinned.

        Returns:
            The reaction volley, or None for a Hold.

        Raises:
            UnmodelledRuleError: the declared reaction is Flee.
        """
        match reaction:
            case StandAndShoot(weapon=weapon):
                self.reaction = stand_and_shoot(
                    self.target, self.charger, weapon, phase_rules=self.shooting_rules
                )
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
    shooting_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
) -> Engagement:
    """Declare and move ``charger``'s charge on ``target`` — a Movement-phase event.

    The charger moves into contact (its movement becomes the charge); the two
    units are now locked in combat. This resolves **no melee** — that is the
    Combat phase (:func:`~avelorn.tow.phases.combat.fight`). The target answers
    on the returned :class:`Engagement` (:meth:`Engagement.react`); a Stand &
    Shoot volley there resolves under ``shooting_rules``.

    Returns:
        The engagement the charge formed, awaiting its reaction and its fight.
    """
    return Engagement(
        charger=charger.charging(move),
        target=target,
        first_round=True,
        shooting_rules=shooting_rules,
    )


@dataclass(frozen=True)
class MovementPhase(Phase):
    """The Movement phase: charges are declared, reacted to, and moved here.

    ``shooting_in_play`` are the *shooting* chapter's rules in force —
    a Stand & Shoot reaction volley resolves under them. The movement
    chapter's own rules have no path into the math yet; when one gains
    effects, this phase grows its own ``in_play`` beside this field.
    """

    shooting_in_play: Mapping[str, Rule]

    def charge(self, charger: Contingent, target: Contingent, move: Charge) -> Engagement:
        """Declare a charge and move it into contact, forming an engagement.

        The target's reaction is declared on the returned engagement
        (:meth:`Engagement.react`), which resolves any Stand & Shoot volley
        under this phase's shooting rules; the Combat phase fights it.

        Returns:
            The engagement the charge formed.
        """
        return charge(charger, target, move, shooting_rules=self.shooting_in_play)
