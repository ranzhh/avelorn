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

from avelorn.tow.combat.context import CombatContext, EngagementContext
from avelorn.tow.combat.contingent import Charge, Contingent
from avelorn.tow.combat.melee import FightResult, fight
from avelorn.tow.combat.shooting import ShootingResult, shoot_unit
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
    moved), so Moving and Shooting does not apply either. The charging unit
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
        context=EngagementContext(moved=False),
        hit_modifier=_STAND_AND_SHOOT_TO_HIT,
        force_short_range=True,
    )


@dataclass(frozen=True)
class StandAndShoot:
    """The Stand & Shoot charge reaction: the target fires as the chargers close."""

    weapon: Weapon  # the missile weapon; must be carried by the reacting unit


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
    reaction: StandAndShoot | None = None,
    phase_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
) -> ChargeResult:
    """Resolve ``charger`` charging ``target``: the reaction, then the fight.

    The sequence as the rulebook plays it. The target answers with its
    declared ``reaction`` — :class:`StandAndShoot`, one volley at the
    closing chargers, or None for Hold (Flee is not modelled yet) — and
    the survivors fight one round of close combat, the chargers'
    Initiative raised by the ``move`` (the-combat-phase/charging-units).
    Each side fights with its chosen Combat weapon. The reaction's
    casualties enter the melee as the chargers' prior losses, so the
    combat result counts only the melee's own wounds.

    Returns:
        The composed outcome: the reaction volley, if any, and the fight.
    """
    volley = None
    if reaction is not None:
        volley = stand_and_shoot(target, charger, reaction.weapon, phase_rules=phase_rules)
    melee = fight(
        charger,
        target,
        a_weapon=charger_weapon,
        b_weapon=target_weapon,
        a_prior_losses=None if volley is None else volley.casualties,
        # A charge sets up a new combat, so the round it feeds is that
        # combat's first — known structurally, not a parameter.
        context=CombatContext(a_charge=move, first_round=True),
    )
    return ChargeResult(reaction=volley, melee=melee)
