"""The charge sequence: the reactions a charge provokes, and the fight it feeds.

A declared charge is answered by a charge reaction before contact
(the-movement-phase/charge-reactions). This module models Stand & Shoot —
the charged unit shooting the chargers as they close — and, later, composes
the survivors into the combat round the charge sets up. The charge's own
Combat-phase Initiative bonus lives on :class:`~avelorn.tow.combat.melee.Charge`.
"""

import logging
from collections.abc import Mapping

from avelorn.tow.combat.context import EngagementContext
from avelorn.tow.combat.melee import Contingent
from avelorn.tow.combat.shooting import ShootingResult, shoot_unit
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.weapon import Weapon

logger = logging.getLogger(__name__)

# Models making a Stand & Shoot reaction suffer -1 To Hit and no Firing at
# Long Range modifier (the-shooting-phase/standing-and-shooting).
_STAND_AND_SHOOT_TO_HIT = -1


def stand_and_shoot(
    shooter: Contingent,
    target: Contingent,
    weapon: Weapon,
    *,
    armoury: Mapping[str, Armour] | None = None,
    rules: Mapping[str, Rule] | None = None,
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
        shooter.unit,
        target.unit,
        shooter.models,
        weapon,
        armoury=armoury,
        rules=rules,
        context=EngagementContext(moved=False),
        hit_modifier=_STAND_AND_SHOOT_TO_HIT,
        force_short_range=True,
        defenders=target.models,
    )
