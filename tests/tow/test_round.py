"""A round of combat fought between two contingents."""

from avelorn.core.distribution import Distribution, Probability
from avelorn.tow.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.programs import ROUND, STAND_AND_SHOOT, load_program
from avelorn.tow.round import fight_round
from avelorn.tow.schema.side import Side
from avelorn.tow.steps import NO_ROLL
from avelorn.tow.volley import stand_and_shoot

REPO = TOWRepository()
ROUND_PROGRAM = load_program(ROUND, REPO.rules)
STAND_AND_SHOOT_PROGRAM = load_program(STAND_AND_SHOOT, REPO.rules)


def _fielded(unit: str, models: int, weapon: str) -> Contingent:
    return Contingent.field(REPO.units[unit], models, data=REPO).wielding(weapon)


def _mass(distribution: Distribution[int]) -> dict[int, Probability]:
    return {outcome: p for outcome, p in distribution.mass.items() if p}


def test_a_charge_counts_in_the_round_of_its_turn() -> None:
    """Spearmen charge Archers 8" into the front, then fight on next turn.

    In the first round the charger strikes at its Initiative 4, +1 for Elven
    Reflexes and +3 for the charge, capped at +3 into the front arc; the
    Archers strike at 4 +1. A later round is fought in a turn the charger did
    not charge, so both strike at 4 and at once (the-combat-phase/charging-units).
    """
    charger = _fielded("elven-spearmen", 10, "Thrusting Spear").charging(
        Charge(8, ChargeArc.FRONT)
    )
    archers = _fielded("elven-archers", 10, "Hand Weapon")

    first = fight_round(ROUND_PROGRAM, charger, archers, first_round=True)
    later = fight_round(ROUND_PROGRAM, charger, archers, first_round=False)

    assert (first.initiative(Side.ATTACKER), first.initiative(Side.TARGET)) == (8, 5)
    assert first.first_striker is Side.ATTACKER
    assert (later.initiative(Side.ATTACKER), later.initiative(Side.TARGET)) == (4, 4)
    assert later.first_striker is None


def test_a_side_takes_up_its_shield_unless_its_weapon_needs_both_hands() -> None:
    """Spearmen struck by a Dwarf Warrior save with light armour and shield on 5+.

    Given great weapons, which Require Two Hands, they leave the shield and
    save on the light armour's 6+.
    """
    datasheet = REPO.units["elven-spearmen"]
    armed = datasheet.model_copy(update={"equipment": [*datasheet.equipment, "Great Weapon"]})
    dwarf = _fielded("dwarf-warriors", 1, "Hand Weapon")
    saves = "round/initiative-2/attacker/attack/dwarf-warrior/make-armour-saves"

    needed = [
        {
            str(score)
            for score in fight_round(
                ROUND_PROGRAM,
                dwarf,
                Contingent.field(armed, 1, data=REPO).wielding(weapon),
                first_round=False,
            )
            .evaluated.at(saves)
            .read("needed")
            .mass
        }
        - {NO_ROLL}
        for weapon in ("Thrusting Spear", "Great Weapon")
    ]

    assert needed == [{"5+"}, {"6+"}]


def test_a_stand_and_shoot_thins_the_chargers_and_scores_for_the_shooters() -> None:
    """Archers stand and shoot at ten Spearmen charging them.

    The round fights on with whoever the volley left, so it is the rounds each
    number of survivors fights, mixed by the volley's chances; the chargers have
    lost the volley's casualties as well. Each Wound the volley caused counts
    toward the Archers' combat result (the-combat-phase/unsaved-wounds-inflicted).
    """
    charger = _fielded("elven-spearmen", 10, "Thrusting Spear").charging(
        Charge(8, ChargeArc.FRONT)
    )
    archers = _fielded("elven-archers", 10, "Hand Weapon")
    stood = stand_and_shoot(STAND_AND_SHOOT_PROGRAM, archers.wielding("Longbow"), charger)

    fought = fight_round(ROUND_PROGRAM, charger, archers, first_round=True, stood=stood)

    left = {
        felled: fight_round(
            ROUND_PROGRAM, charger.remove_casualties(felled), archers, first_round=True
        )
        for felled in stood.casualties.mass
    }
    lost = stood.casualties.bind(
        lambda felled: left[felled].casualties(Side.ATTACKER).map(lambda melee: melee + felled)
    )
    margin = stood.casualties.bind(
        lambda felled: left[felled].margin.map(lambda lead: lead - felled)
    )
    assert _mass(fought.casualties(Side.ATTACKER)) == _mass(lost)
    assert _mass(fought.margin) == _mass(margin)


def test_a_stand_and_shoot_scores_only_in_the_turn_it_was_made() -> None:
    """Archers stood and shot at ten Spearmen charging them, and the combat fights on next turn.

    The round fights on with whoever the volley left, but its Wounds were lost
    in an earlier turn, so they count toward no combat result now
    (the-combat-phase/unsaved-wounds-inflicted).
    """
    charger = _fielded("elven-spearmen", 10, "Thrusting Spear").charging(
        Charge(8, ChargeArc.FRONT)
    )
    archers = _fielded("elven-archers", 10, "Hand Weapon")
    stood = stand_and_shoot(STAND_AND_SHOOT_PROGRAM, archers.wielding("Longbow"), charger)

    fought = fight_round(ROUND_PROGRAM, charger, archers, first_round=False, stood=stood)

    left = {
        felled: fight_round(
            ROUND_PROGRAM, charger.remove_casualties(felled), archers, first_round=False
        )
        for felled in stood.casualties.mass
    }
    margin = stood.casualties.bind(lambda felled: left[felled].margin)
    assert _mass(fought.margin) == _mass(margin)


def test_a_champion_fights_with_its_own_attacks() -> None:
    """Ten Dwarf Warriors fight their like, both striking at Initiative 2.

    Heavy Infantry stand four to a rank: four in the front rank at A1 and four
    supporting make 8 attacks. A Veteran at A2 stands in the front rank, so it
    makes 9.
    """
    foes = Contingent.deploy("dwarf-warriors", 10, data=REPO).wielding("Hand Weapon")
    attacks = "round/initiative-2/attacker/how-many-attacks"

    made = [
        fight_round(
            ROUND_PROGRAM,
            Contingent.deploy("dwarf-warriors", 10, options, data=REPO).wielding("Hand Weapon"),
            foes,
            first_round=True,
        )
        .evaluated.at(attacks)
        .read("attacks")
        .mass
        for options in ((), ("veteran",))
    ]

    assert made == [{8: 1}, {9: 1}]


def test_a_champion_stands_and_shoots_at_its_own_ballistic_skill() -> None:
    """Ten Archers five wide with a Sentinel stand and shoot at charging Spearmen.

    Only the front rank shoots, the Sentinel among it. Stand & Shoot's -1 To
    Hit takes the Sentinel's BS 5 to 3+ and the Archers' BS 4 to 4+.
    """
    charger = _fielded("elven-spearmen", 10, "Thrusting Spear").charging(
        Charge(8, ChargeArc.FRONT)
    )
    archers = Contingent.deploy("elven-archers", 10, ("sentinel",), data=REPO, frontage=5)

    stood = stand_and_shoot(STAND_AND_SHOOT_PROGRAM, archers.wielding("Longbow"), charger)

    shots = stood.evaluated.at("stand-and-shoot/how-many-shots").read("parts").mass
    sentinel = stood.evaluated.at("stand-and-shoot/attacker/attack/sentinel/roll-to-hit")
    assert shots == {"sentinel 1, elven-archer 4": 1}
    assert sentinel.read("needed").mass == {"3+": 1}
    assert stood.needed("roll-to-hit") == "4+"
