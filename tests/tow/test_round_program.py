"""A round of close combat on the graph."""

from fractions import Fraction

import pytest

from avelorn.core.distribution import Probability
from avelorn.core.graph import Decision
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.fielding import Fielding
from avelorn.tow.programs import ROUND, Evaluated, Loaded, load_program
from avelorn.tow.schema.effect import Role
from avelorn.tow.schema.rule import Clause, RuleGraph
from avelorn.tow.schema.stage import Side
from avelorn.tow.steps import NO_ROLL

REPO = TOWRepository()
ROUND_PROGRAM = load_program(ROUND, REPO.rules)
WITHOUT_MARTIAL_PROWESS = load_program(
    ROUND, {**REPO.rules, "martial-prowess": REPO.rules["martial-prowess"].with_graph(None)}
)


def _fielded(unit: str, weapon: str, models: int, frontage: int | None = None) -> Fielding:
    contingent = Contingent.field(REPO.units[unit], models, data=REPO, frontage=frontage)
    return Fielding.of(contingent, weapon, combat=True)


def _fought(
    attacker: Fielding,
    target: Fielding,
    attacker_standing: int = 1,
    program: Loaded = ROUND_PROGRAM,
    attacker_charges: int = 0,
    rounds_fought: int = 1,
) -> Evaluated:
    built = program.built({Side.ATTACKER: attacker, Side.TARGET: target})
    (evaluated,) = built.evaluate(
        {
            "attacker/standing": attacker.standing(attacker_standing),
            "target/standing": target.standing(sum(part.count for part in target.parts)),
            "attacker/rounds-fought": rounds_fought,
            "target/rounds-fought": rounds_fought,
            "attacker/charges-made": attacker_charges,
            "target/charges-made": 0,
        }
    )
    return evaluated


def _falls(fought: Evaluated, side: Side) -> Probability:
    return fought.at(f"round/initiative-1/{side}/remove-casualties").read("models").mass[0]


def _needed(fought: Evaluated, path: str) -> set[str]:
    shown = fought.at(path).read("needed").mass
    return {str(each) for each in shown} - {NO_ROLL}


def test_equal_initiative_strikes_at_once() -> None:
    """One Elven Spearman a side, both Initiative 4, strike from the same standings.

    Weapon Skill 4 against 4 hits on 4+ (1/2), Strength 3 against Toughness 3
    wounds on 4+ (1/2), and light armour with a shield saves on 5+ (fails 2/3):
    each falls on 1/6, as neither blow waits for the other.
    """
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)

    fought = _fought(spearman, spearman)

    assert _falls(fought, Side.ATTACKER) == _falls(fought, Side.TARGET) == Fraction(1, 6)


def test_the_higher_initiative_strikes_first() -> None:
    """An Elven Spearman (I4) strikes before the Dwarf Warrior (I2) attacking it.

    The Spearman hits on 4+ (1/2), wounds Toughness 4 on 5+ (1/3) and beats
    heavy armour's 5+ save on 2/3: the Dwarf falls on 1/9. The Dwarf swings
    back only while it stands (8/9), hitting on 4+, wounding on 4+ and beating
    the 5+ save on 1/6: the Spearman falls on 8/9 * 1/6 = 4/27.
    """
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)

    fought = _fought(dwarf, spearman)

    assert _falls(fought, Side.ATTACKER) == Fraction(1, 9)
    assert _falls(fought, Side.TARGET) == Fraction(4, 27)


def test_a_fighting_rank_model_that_falls_takes_its_attacks() -> None:
    """Fifteen Spearmen five wide that charged and lost three this round throw 2 attacks, not 5.

    On the turn they charged, Who Can Fight names the front rank alone, and a
    casualty suffered in the round comes off it before the rear rank (FAQ v1.5.3).
    """
    spearmen = _fielded("elven-spearmen", "Thrusting Spear", 15, frontage=5)
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)

    fought = _fought(spearmen, dwarf, attacker_standing=12, attacker_charges=1)

    attacks = fought.at("round/initiative-4/attacker/how-many-attacks").read("attacks")
    assert attacks.mass == {2: 1}


def test_an_entry_acting_for_the_target_swaps_the_sides() -> None:
    """The target's attack group holds its part as the attacker, and its rules land on its steps.

    Without the swap, the Spearman's blow would wound as the Dwarf's does, Strength
    3 against Toughness 3 on 4+; it wounds Toughness 4 on 5+. Elven Reflexes, the
    Spearmen's own, lands on the target's Who Strikes First alone.
    """
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)

    fought = _fought(dwarf, spearman)

    wound = fought.at("round/initiative-4/target/attack/elven-spearman/roll-to-wound")
    assert wound.read("needed").mass == {"5+": 1}
    program = fought.built.program
    reflexes = program.rules["target/elven-spearmen/elven-reflexes"]
    assert [program.paths[landing.at] for landing in reflexes.landings] == [
        "round/target/who-strikes-first"
    ]


@pytest.mark.parametrize(
    ("foe", "program", "rounds_fought", "striking", "needed"),
    [
        pytest.param("longbeards", ROUND_PROGRAM, 0, 5, ({"4+"}, {"4+"}), id="ws5-first-round"),
        pytest.param("longbeards", ROUND_PROGRAM, 1, 4, ({"4+"}, {"3+"}), id="ws5-later-round"),
        pytest.param(
            "longbeards",
            WITHOUT_MARTIAL_PROWESS,
            0,
            5,
            ({"4+"}, {"3+"}),
            id="ws5-without-the-rule",
        ),
        pytest.param(
            "dwarf-warriors", ROUND_PROGRAM, 0, 5, ({"3+"}, {"4+"}), id="ws4-first-round"
        ),
        pytest.param(
            "dwarf-warriors",
            WITHOUT_MARTIAL_PROWESS,
            0,
            5,
            ({"4+"}, {"4+"}),
            id="ws4-without-the-rule",
        ),
    ],
)
def test_martial_prowess_moves_weapon_skill_striking_and_struck(
    foe: str,
    program: Loaded,
    rounds_fought: int,
    striking: int,
    needed: tuple[set[str], set[str]],
) -> None:
    """Elven Spearmen count as WS5 in the first round, striking and struck, ten a side in a rank.

    On the chart WS5 against WS5 Longbeards hits on 4+ both ways. At WS4, in a
    later round or without the rule, the Spearmen still hit WS5 on 4+, and the
    Longbeards' WS5 hits WS4 on 3+. Against WS4 Dwarf Warriors the Spearmen hit
    on 3+ at WS5 and on 4+ at WS4, and are hit on 4+ either way. The Spearmen
    strike at Initiative 5 in the first round and at 4 after it; a foe felled
    before its blow at 2 rolls nothing.
    """
    spearmen = _fielded("elven-spearmen", "Hand Weapon", 10, frontage=10)
    dwarfs = _fielded(foe, "Hand Weapon", 10, frontage=10)
    (dwarf,) = dwarfs.parts

    fought = _fought(
        spearmen, dwarfs, attacker_standing=10, program=program, rounds_fought=rounds_fought
    )

    assert (
        _needed(fought, f"round/initiative-{striking}/attacker/attack/elven-spearman/roll-to-hit"),
        _needed(fought, f"round/initiative-2/target/attack/{dwarf.id}/roll-to-hit"),
    ) == needed


def test_a_list_of_sides_builds_the_entry_once_for_each_in_order() -> None:
    """Both sides decide and measure at the head; the target's casualties come off first."""
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)

    program = ROUND_PROGRAM.built({Side.ATTACKER: spearman, Side.TARGET: spearman}).program

    paths = [program.paths[step] for step in program.steps]
    assert paths[:6] == [
        "round/attacker/choose-combat-and-determine-who-can-fight",
        "round/target/choose-combat-and-determine-who-can-fight",
        "round/attacker/who-can-fight",
        "round/target/who-can-fight",
        "round/attacker/who-strikes-first",
        "round/target/who-strikes-first",
    ]
    assert [
        path
        for path in paths
        if path.startswith("round/initiative-4/") and path.endswith("/remove-casualties")
    ] == [
        "round/initiative-4/target/remove-casualties",
        "round/initiative-4/attacker/remove-casualties",
    ]


def test_a_side_chooses_each_weapon_it_carries_with_or_without_its_shield() -> None:
    """Elven Spearmen given great weapons may fight with any weapon they carry, shield or not."""
    datasheet = REPO.units["elven-spearmen"]
    armed = datasheet.model_copy(update={"equipment": [*datasheet.equipment, "Great Weapon"]})
    spearmen = Fielding.of(Contingent.field(armed, 10, data=REPO), "Great Weapon", combat=True)

    choice = _fought(spearmen, spearmen).at(
        "round/target/choose-combat-and-determine-who-can-fight"
    )

    assert isinstance(choice.step, Decision)
    assert [str(option) for option in choice.step.options] == [
        "hand-weapon",
        "hand-weapon+shield",
        "thrusting-spear",
        "thrusting-spear+shield",
        "great-weapon",
        "great-weapon+shield",
    ]


def test_a_rule_two_carried_weapons_give_is_in_force_once_in_each_option() -> None:
    """Spearmen given a great weapon and a halberd attach Requires Two Hands, which both give.

    No option holds both weapons, so each sees the rule once, as each sees
    Fight in Extra Rank from the spear or the halberd once. Swinging the great
    weapon, the Spearmen take it without their shield.
    """
    datasheet = REPO.units["elven-spearmen"]
    two_handed = ["Great Weapon", "Ceremonial Halberd"]
    armed = datasheet.model_copy(update={"equipment": [*datasheet.equipment, *two_handed]})
    spearmen = Fielding.of(Contingent.field(armed, 1, data=REPO), "Great Weapon", combat=True)

    choice = _fought(spearmen, spearmen).at(
        "round/target/choose-combat-and-determine-who-can-fight"
    )

    assert {str(taken.option) for taken in choice.read("taken").mass} == {"great-weapon"}


def test_the_target_s_part_reads_its_weapon_strength_at_its_own_blow() -> None:
    """A Swordmaster striking back wounds at the Sword of Hoeth's S+2, so 5, not its printed 3.

    At its own roll To Wound the Swordmaster plays the attacker: Strength 5
    against the Spearman's Toughness 3 wounds on 2+.
    """
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)
    swordmaster = _fielded("swordmasters-of-hoeth", "Sword of Hoeth", 1)

    wound = _fought(spearman, swordmaster).at(
        "round/initiative-6/target/attack/swordmaster/roll-to-wound"
    )

    assert wound.read("needed").mass == {"2+": 1}


def test_the_target_s_magical_blows_meet_no_runes_of_protection() -> None:
    """The Swordmasters' magical blows meet no 6+ ward from the Ironbreakers they strike back at.

    The Runes of Protection ward only a non-magical attack, and the attack is the
    Swordmasters' own, not the Ironbreakers'.
    """
    ironbreaker = _fielded("ironbreakers", "Hand Weapon", 1)
    swordmaster = _fielded("swordmasters-of-hoeth", "Sword of Hoeth", 1)

    ward = _fought(ironbreaker, swordmaster).at(
        "round/initiative-6/target/attack/swordmaster/ward-saves"
    )

    assert ward.read("needed").mass == {"-": 1}


def test_a_strength_change_of_the_model_struck_is_held_at_the_blow() -> None:
    """Enfeebling Cold rewritten to lower the Merwyrm's own Strength leaves the Lions' blow alone.

    The White Lions' roll To Wound folds the Strength of the Lions striking: their
    great blade's 6 against Toughness 6 wounds on 4+. The blade strikes last, and
    the Merwyrm's four Attacks before it leave one of a rank of five standing.
    """
    printed = REPO.rules["enfeebling-cold"]
    assert printed.graph is not None
    (effect,) = printed.graph.effects
    own = effect.model_copy(update={"of": Role.THIS_MODEL})
    rules = {
        **REPO.rules,
        "enfeebling-cold": printed.with_graph(RuleGraph(clauses=(Clause(effect=own),))),
    }
    lions = _fielded("white-lions-of-chrace", "Chracian Great Blade", 5, frontage=5)
    merwyrm = _fielded("merwyrm", "Lashing Talons", 1)

    fought = _fought(lions, merwyrm, attacker_standing=5, program=load_program(ROUND, rules))

    wound = fought.at("round/initiative-1/attacker/attack/white-lion/roll-to-wound")
    assert wound.read("needed").mass == {"4+": 1}
