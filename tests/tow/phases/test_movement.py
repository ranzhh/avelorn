"""The Movement phase: the charge, its reactions, and the engagement it forms."""

import pytest

from avelorn.core.distribution import Distribution, Probability
from avelorn.core.errors import UnmodelledRuleError
from avelorn.tow.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.phases.combat import CombatPhase
from avelorn.tow.phases.movement import Flee, StandAndShoot, charge
from avelorn.tow.programs import ROUND, STAND_AND_SHOOT, load_program
from avelorn.tow.schema.side import Side
from avelorn.tow.schema.unit import Unit

REPO = TOWRepository()

STAND_AND_SHOOT_PROGRAM = load_program(STAND_AND_SHOOT, REPO.rules)

COMBAT = CombatPhase(program=load_program(ROUND, REPO.rules))


def _fielded(unit: Unit, models: int) -> Contingent:
    # Field at the printed, optionless loadout, with the real registries.
    return Contingent.field(unit, models, data=REPO)


def _mass(distribution: Distribution[int]) -> dict[int, Probability]:
    return {outcome: p for outcome, p in distribution.mass.items() if p}


# --- charge(): the Movement-phase charge, its reaction, and the engagement ---


def test_charge_forms_an_engagement_and_its_reaction() -> None:
    """charge() forms an engagement; react() resolves the Stand & Shoot volley.

    The charge is a Movement-phase event only: it locks the units in combat
    (the charger entering carrying its charge) and records the target's
    reaction on the engagement. No melee is fought here.
    """
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    charger, target = _fielded(spearmen, 10), _fielded(archers, 10)
    move = Charge(8, ChargeArc.FRONT)

    engagement = charge(charger, target, move, program=STAND_AND_SHOOT_PROGRAM)
    fired = engagement.react(StandAndShoot("Longbow"))

    assert engagement.a.movement.charge == move
    assert engagement.b is target
    assert fired is not None
    assert engagement.reaction is fired


def test_stand_and_shoot_defaults_to_the_sole_missile_weapon() -> None:
    """StandAndShoot() with no weapon fires the reacting unit's only missile weapon.

    The target holds a Hand Weapon for the ensuing melee, but the reaction
    ignores that arm and fires its sole bow — the same volley as naming it.
    """
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    charger = _fielded(spearmen, 10).wielding("Thrusting Spear")
    target = _fielded(archers, 10).wielding("Hand Weapon")
    move = Charge(8, ChargeArc.FRONT)

    named = charge(charger, target, move, program=STAND_AND_SHOOT_PROGRAM).react(
        StandAndShoot("Longbow")
    )
    default = charge(charger, target, move, program=STAND_AND_SHOOT_PROGRAM).react(StandAndShoot())
    assert named is not None
    assert default is not None
    assert _mass(default.casualties) == _mass(named.casualties)


def test_the_engagement_is_fought_in_its_first_round_until_the_turn_ends() -> None:
    """Spearmen charge Archers 8" into the front, then fight on after the turn ends.

    The charge's round is the first: the charger strikes at its Initiative 4,
    +1 for Elven Reflexes and +3 for the charge. Next turn neither applies
    (the-combat-phase/charging-units).
    """
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    charger = _fielded(spearmen, 10).wielding("Thrusting Spear")
    target = _fielded(archers, 10).wielding("Hand Weapon")
    engagement = charge(
        charger, target, Charge(8, ChargeArc.FRONT), program=STAND_AND_SHOOT_PROGRAM
    )
    engagement.react()

    first = COMBAT.fight(engagement).initiative(Side.ATTACKER)
    engagement.end_turn()
    later = COMBAT.fight(engagement).initiative(Side.ATTACKER)

    assert (first, later) == (8, 4)


def test_a_held_charge_fights_with_no_prior_losses() -> None:
    """Hold: no reaction volley, and the engagement's fight is the plain charge."""
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    charger = _fielded(spearmen, 10).wielding("Thrusting Spear")
    target = _fielded(archers, 10).wielding("Hand Weapon")
    move = Charge(8, ChargeArc.FRONT)

    engagement = charge(charger, target, move, program=STAND_AND_SHOOT_PROGRAM)
    engagement.react()
    outcome = COMBAT.fight(engagement)

    plain = COMBAT.fight(charger.charging(move), target)
    assert engagement.reaction is None
    assert _mass(outcome.margin(Side.ATTACKER)) == _mass(plain.margin(Side.ATTACKER))


def test_the_reaction_vocabulary_is_the_printed_three() -> None:
    """Hold is the default and takes no volley; Flee is a loud error.

    "There are three charge reactions available to the inactive player:
    Hold, Stand & Shoot and Flee" (the-movement-phase/charge-reactions).
    Flee is in the vocabulary but not modelled, and refusing loudly
    beats resolving a charge whose target silently stood still.
    """
    charger = _fielded(REPO.units["elven-spearmen"], 5)
    target = _fielded(REPO.units["elven-archers"], 5)
    move = Charge(3, ChargeArc.FRONT)

    held = charge(charger, target, move, program=STAND_AND_SHOOT_PROGRAM)
    assert held.react() is None  # Hold: the default, no volley
    with pytest.raises(UnmodelledRuleError, match="Flee"):
        charge(charger, target, move, program=STAND_AND_SHOOT_PROGRAM).react(Flee())


def test_end_turn_ages_the_engagement_out_of_its_first_round() -> None:
    """A charge forms a first-round engagement; end_turn clears the flag.

    The combat persists, so next turn it is no longer the charge's first
    round — the charge bonus and first-round rules lapse.
    """
    charger = _fielded(REPO.units["elven-spearmen"], 5)
    target = _fielded(REPO.units["elven-archers"], 5)
    engagement = charge(
        charger, target, Charge(3, ChargeArc.FRONT), program=STAND_AND_SHOOT_PROGRAM
    )
    assert engagement.first_round is True
    engagement.end_turn()
    assert engagement.first_round is False
