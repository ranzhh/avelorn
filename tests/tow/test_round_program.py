"""A round of close combat on the graph."""

from fractions import Fraction

from avelorn.core.distribution import Distribution, Probability
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.fielding import Fielding
from avelorn.tow.programs import ROUND, Evaluated, Loaded, load_program
from avelorn.tow.schema.effect import Role
from avelorn.tow.schema.rule import Clause, RuleGraph
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.traits import Operand

REPO = TOWRepository()
ROUND_PROGRAM = load_program(ROUND, REPO.rules)


def _fielded(unit: str, weapon: str, models: int, frontage: int | None = None) -> Fielding:
    contingent = Contingent.field(REPO.units[unit], models, data=REPO, frontage=frontage)
    return Fielding.of(contingent, weapon, combat=True)


def _fought(
    attacker: Fielding,
    target: Fielding,
    attacker_standing: int = 1,
    program: Loaded = ROUND_PROGRAM,
    attacker_charges: int = 0,
) -> Evaluated:
    built = program.built({Side.ATTACKER: attacker, Side.TARGET: target})
    (evaluated,) = built.evaluate(
        {
            "attacker/standing": attacker.standing(attacker_standing),
            "target/standing": target.standing(sum(part.count for part in target.parts)),
            "attacker/rounds-fought": 1,
            "target/rounds-fought": 1,
            "attacker/charges-made": attacker_charges,
            "target/charges-made": 0,
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


def test_a_list_of_sides_builds_the_entry_once_for_each_in_order() -> None:
    """Both sides measure at the head; the target's casualties come off before the attacker's."""
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)

    program = ROUND_PROGRAM.built({Side.ATTACKER: spearman, Side.TARGET: spearman}).program

    paths = [program.paths[step] for step in program.steps]
    assert paths[:4] == [
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


def test_the_target_s_part_reads_its_weapon_strength_at_its_own_blow() -> None:
    """A Swordmaster striking back wounds at the Sword of Hoeth's S+2, so 5, not its printed 3.

    At its own roll To Wound the Swordmaster plays the attacker.
    """
    spearman = _fielded("elven-spearmen", "Thrusting Spear", 1)
    swordmaster = _fielded("swordmasters-of-hoeth", "Sword of Hoeth", 1)

    wound = _fought(spearman, swordmaster).at(
        "round/initiative-6/target/attack/swordmaster/roll-to-wound"
    )

    assert wound.part(Side.TARGET, "swordmaster").characteristic(
        Characteristic.STRENGTH
    ) == Operand(Distribution.pure(5), 3)


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
