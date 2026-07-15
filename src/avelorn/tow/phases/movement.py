"""The charge sequence: a unit charges another, and the situation unfolds.

:func:`charge` is the verb — ``charger`` charges ``target``, the target
answers with a reaction (the-movement-phase/charge-reactions), and the
survivors fight the round the charge set up, the chargers' Initiative
raised by the move. The reactions modelled: :class:`StandAndShoot` and
Hold (Flee is not, yet). :func:`stand_and_shoot` resolves the reaction
volley itself and stays callable on its own.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import assert_never

from avelorn.core.errors import UnmodelledRuleError
from avelorn.core.game import Phase
from avelorn.tow.contingent import Charge, Contingent
from avelorn.tow.phases.combat import FightResult, fight
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


@dataclass(frozen=True)
class ChargeResult:
    """A charge sequence resolved: the reaction volley and the fight it fed.

    ``reaction`` is the Stand & Shoot outcome, or None when the target
    Held; its casualties entered the melee as the chargers' prior
    losses. ``melee`` is the round the survivors fought.
    """

    reaction: ShootingResult | None
    melee: FightResult


def charge(
    charger: Contingent,
    target: Contingent,
    *,
    move: Charge,
    charger_weapon: Weapon,
    target_weapon: Weapon,
    reaction: ChargeReaction = HOLD,
    phase_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
) -> ChargeResult:
    """Resolve ``charger`` charging ``target``: the reaction, then the fight.

    The sequence as the rulebook plays it. The target answers with its
    declared ``reaction`` — one of the printed three: :class:`Hold`,
    :class:`StandAndShoot` (one volley at the closing chargers), or
    :class:`Flee` (a loud error until it is modelled) — and the
    survivors fight one round of close combat, the chargers'
    Initiative raised by the ``move`` (the-combat-phase/charging-units).
    Each side fights with its chosen Combat weapon. The reaction's
    casualties enter the melee as the chargers' prior losses, so the
    combat result counts only the melee's own wounds.

    Returns:
        The composed outcome: the reaction volley, if any, and the fight.

    Raises:
        UnmodelledRuleError: the declared reaction is Flee, which is
            not modelled yet.
    """
    volley = None
    match reaction:
        case StandAndShoot(weapon=weapon):
            volley = stand_and_shoot(target, charger, weapon, phase_rules=phase_rules)
        case Flee():
            raise UnmodelledRuleError("the Flee charge reaction is not modelled yet")
        case Hold():
            pass
        case unanswered:
            # A reaction joining the vocabulary must be answered here —
            # a charge whose target silently did nothing is the wrong game.
            assert_never(unanswered)
    melee = fight(
        charger.charging(move),
        target,
        a_weapon=charger_weapon,
        b_weapon=target_weapon,
        a_prior_losses=None if volley is None else volley.casualties,
        # A charge sets up a new combat, so the round it feeds is that
        # combat's first — known structurally, not a parameter to guess.
        first_round=True,
    )
    return ChargeResult(reaction=volley, melee=melee)


@dataclass(frozen=True)
class MovementPhase(Phase):
    """The Movement phase: the charge, and the reactions that answer it.

    ``shooting_in_play`` are the *shooting* chapter's rules in force —
    a Stand & Shoot reaction volley resolves under them. The movement
    chapter's own rules have no path into the math yet; when one gains
    effects, this phase grows its own ``in_play`` beside this field.
    """

    shooting_in_play: Mapping[str, Rule]

    def charge(
        self,
        charger: Contingent,
        target: Contingent,
        *,
        move: Charge,
        charger_weapon: Weapon,
        target_weapon: Weapon,
        reaction: ChargeReaction = HOLD,
    ) -> ChargeResult:
        """A charge is declared, answered, and driven home.

        The Stand & Shoot reaction volley resolves under the shooting
        chapter's rules. The fight the charge feeds does not yet see the
        combat chapter's rules: the charge threads only the shooting rules
        it holds, and wiring the combat rules through waits until a combat
        chapter rule has effects to honour.

        Returns:
            The composed outcome: the reaction volley, if any, and the fight.
        """
        return charge(
            charger,
            target,
            move=move,
            charger_weapon=charger_weapon,
            target_weapon=target_weapon,
            reaction=reaction,
            phase_rules=self.shooting_in_play,
        )

    def stand_and_shoot(
        self,
        shooter: Contingent,
        target: Contingent,
        weapon: Weapon,
    ) -> ShootingResult:
        """The Stand & Shoot charge reaction: one volley at the closing chargers.

        Returns:
            The volley's outcome — chargers felled before they strike.
        """
        return stand_and_shoot(shooter, target, weapon, phase_rules=self.shooting_in_play)
