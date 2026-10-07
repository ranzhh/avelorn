"""A round of close combat on the graph, with no rule applied."""

from fractions import Fraction

from avelorn.core.distribution import Probability
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.fielding import Fielding
from avelorn.tow.programs import ROUND, Evaluated, load_program
from avelorn.tow.schema.stage import Side

REPO = TOWRepository()
ROUND_PROGRAM = load_program(ROUND, REPO.rules)


def _fielded(unit: str, weapon: str, models: int, frontage: int | None = None) -> Fielding:
    contingent = Contingent.field(REPO.units[unit], models, data=REPO, frontage=frontage)
    return Fielding.of(contingent, weapon, combat=True)


def _fought(attacker: Fielding, target: Fielding, attacker_standing: int = 1) -> Evaluated:
    built = ROUND_PROGRAM.built({Side.ATTACKER: attacker, Side.TARGET: target})
    (evaluated,) = built.evaluate(
        {
            "attacker/standing": attacker.standing(attacker_standing),
            "target/standing": target.standing(sum(part.count for part in target.parts)),
        }
    )
    return evaluated


def _falls(fought: Evaluated, side: Side) -> Probability:
    return fought.at(f"round/initiative-1/{side}/remove-casualties").read("models").mass[0]


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
    """Fifteen Spearmen five wide that lost three this round throw 2 attacks, not 5.

    Who Can Fight prints the fighting rank alone, and a casualty suffered in the
    round comes off it before the rear rank (FAQ v1.5.3).
    """
    spearmen = _fielded("elven-spearmen", "Thrusting Spear", 15, frontage=5)
    dwarf = _fielded("dwarf-warriors", "Hand Weapon", 1)

    fought = _fought(spearmen, dwarf, attacker_standing=12)

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
