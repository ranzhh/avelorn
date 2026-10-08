"""Each rule that changes who fights, how often or in what order, fought with and without it."""

from dataclasses import replace
from fractions import Fraction

import pytest
from oracle.procedure import Attack, Phase, casualties, exchange, one_attack

from rules.scenario import Kind, Ref, Role, Scenario, Side, resolve

COMBAT = Phase.COMBAT
SPEARMEN = Side("elven-spearmen", 10, "Thrusting Spear")
DWARFS = Side("dwarf-warriors", 10, "Hand Weapon", frontage=5)
FROSTHEART = Side("frostheart-phoenix", 1, "Wicked Claws")


def _attacks(printed: Scenario, plain: Scenario) -> tuple[object, object]:
    return resolve(printed).attacks, resolve(plain).attacks


@pytest.mark.parametrize(
    ("charged", "printed", "plain"),
    [
        pytest.param(None, 2 * 5 + 5, 2 * 5, id="stationary"),
        pytest.param(5, 5, 5, id="charged"),
    ],
)
def test_fight_in_extra_rank(charged: int | None, printed: int, plain: int) -> None:
    """Behind two fighting ranks of five, the third rank's spears make a supporting attack each.

    Not on the turn the spearmen charged, when one rank fights.
    """
    spears = Side("elven-spearmen", 15, "Thrusting Spear", frontage=5, charged=charged)
    scenario = Scenario(Kind.STRIKE, spears, SPEARMEN)
    assert _attacks(scenario, scenario.without("fight-in-extra-rank", Role.ATTACKER)) == (
        printed,
        plain,
    )


@pytest.mark.parametrize(
    ("charged", "printed", "plain"),
    [
        pytest.param(
            5,
            2 * 5,
            5,
            id="charged-5-inches",
            marks=pytest.mark.xfail(
                strict=True, reason="Furious Charge needs the charge move at How Many Attacks"
            ),
        ),
        pytest.param(2, 5, 5, id="charged-2-inches"),
        pytest.param(None, 2 * 5, 2 * 5, id="did-not-charge"),
    ],
)
def test_furious_charge(charged: int | None, printed: int, plain: int) -> None:
    """A front rank of five White Lions that charged 3" or more makes two Attacks each, not one.

    Not charging, both ranks fight at one Attack each.
    """
    lions = Side("white-lions-of-chrace", 10, "Hand Weapon", frontage=5, charged=charged)
    scenario = Scenario(Kind.STRIKE, lions, SPEARMEN)
    assert _attacks(scenario, scenario.without("furious-charge", Role.ATTACKER)) == (
        printed,
        plain,
    )


@pytest.mark.parametrize(
    ("charged", "printed"),
    [
        pytest.param(None, 2 * 5, id="stationary"),
        pytest.param(5, 5, id="charged"),
    ],
)
def test_press_of_battle(charged: int | None, printed: int) -> None:
    """Two ranks of five fight rather than one, except on the turn the unit charged."""
    swords = Side("elven-spearmen", 15, "Hand Weapon", frontage=5, charged=charged)
    scenario = Scenario(Kind.STRIKE, swords, SPEARMEN)
    assert _attacks(scenario, scenario.without("press-of-battle", Role.ATTACKER)) == (printed, 5)


DUEL = Side("elven-spearmen", 1, "Hand Weapon", frontage=1)
DUEL_BLOW = Attack(COMBAT, 4, 3, 3, foe_weapon_skill=4, armour_value=4)
FELLS = one_attack(DUEL_BLOW).unsaved
HIT_FELLS = one_attack(replace(DUEL_BLOW, automatic_hit=True)).unsaved
OUTLASTS_D6_HITS = sum(Fraction(1, 6) * (1 - HIT_FELLS) ** hits for hits in range(1, 7))


@pytest.mark.parametrize(
    ("charged", "first_round", "printed", "plain"),
    [
        pytest.param(
            6,
            True,
            (1 - OUTLASTS_D6_HITS * (1 - FELLS), OUTLASTS_D6_HITS * (1 - FELLS) * FELLS),
            (FELLS, (1 - FELLS) * FELLS),
            id="charged-6-inches",
        ),
        pytest.param(
            2,
            True,
            (FELLS, (1 - FELLS) * FELLS),
            (FELLS, (1 - FELLS) * FELLS),
            id="charged-2-inches",
        ),
        pytest.param(None, False, (FELLS, FELLS), (FELLS, FELLS), id="standing"),
    ],
)
def test_impact_hits(
    charged: int | None,
    first_round: bool,
    printed: tuple[Fraction, Fraction],
    plain: tuple[Fraction, Fraction],
) -> None:
    """A spearman that charged 3" or more causes D6 automatic S3 hits before any blow.

    One spearman a side, each blow and each hit felling on 4+, 4+ and a failed 4+ save
    (WS4 against WS4, or WS5 against WS5 in the first round). The charger strikes
    first, and the foe strikes back only if it still stands; standing, both strike
    together.
    """
    scenario = Scenario(Kind.FIGHT, replace(DUEL, charged=charged), DUEL, first_round=first_round)
    struck = resolve(scenario.adding("impact-hits", Role.ATTACKER, x="D6"))
    bare = resolve(scenario)
    assert (struck.casualties[1], struck.attacker_casualties[1]) == printed
    assert (bare.casualties[1], bare.attacker_casualties[1]) == plain


def _losses(blow: Attack, back: Attack) -> tuple[dict[int, Fraction], dict[int, Fraction]]:
    foe_lost: dict[int, Fraction] = {}
    own_lost: dict[int, Fraction] = {}
    for (felled, lost), p in exchange(one_attack(blow), one_attack(back), models=10).items():
        foe_lost[felled] = foe_lost.get(felled, Fraction(0)) + p
        own_lost[lost] = own_lost.get(lost, Fraction(0)) + p
    return foe_lost, own_lost


@pytest.mark.parametrize(
    ("foe", "first_round", "blow", "back"),
    [
        pytest.param(
            "dwarf-warriors",
            True,
            Attack(COMBAT, 4, 3, 4, foe_weapon_skill=4, armour_value=5),
            Attack(COMBAT, 4, 3, 3, foe_weapon_skill=4, armour_value=4),
            id="striking-ws4-first-round",
        ),
        pytest.param(
            "longbeards",
            True,
            Attack(COMBAT, 4, 3, 4, foe_weapon_skill=5, armour_value=5),
            Attack(COMBAT, 5, 4, 3, foe_weapon_skill=4, armour_value=4, armour_piercing=-1),
            id="struck-by-ws5-first-round",
        ),
        pytest.param(
            "longbeards",
            False,
            Attack(COMBAT, 4, 3, 4, foe_weapon_skill=5, armour_value=5),
            Attack(COMBAT, 5, 4, 3, foe_weapon_skill=4, armour_value=4, armour_piercing=-1),
            id="later-round",
        ),
    ],
)
def test_martial_prowess(foe: str, first_round: bool, blow: Attack, back: Attack) -> None:
    """Spearmen count as WS5 in the first round, striking and struck.

    Ten a side in one rank; the Spearmen strike first and the Dwarfs' survivors strike
    back. WS5 hits WS4 Dwarfs on 3+ rather than 4+, and WS5 Longbeards hit it on 4+
    rather than 3+.
    """
    swords = Side("elven-spearmen", 10, "Hand Weapon", frontage=10)
    dwarfs = Side(foe, 10, "Hand Weapon", frontage=10)
    scenario = Scenario(Kind.FIGHT, swords, dwarfs, first_round=first_round)
    skill = 5 if first_round else 4
    printed = resolve(scenario)
    plain = resolve(scenario.without("martial-prowess", Role.ATTACKER))
    assert (
        (printed.casualties, printed.attacker_casualties),
        (plain.casualties, plain.attacker_casualties),
    ) == (
        _losses(replace(blow, skill=skill), replace(back, foe_weapon_skill=skill)),
        _losses(blow, back),
    )


def _once(p: Fraction) -> dict[int, Fraction]:
    return {0: 1 - p, 1: p}


CLAWS = one_attack(Attack(COMBAT, 6, 6, 3, foe_weapon_skill=4, armour_value=5, armour_piercing=-2))
STOMP = one_attack(Attack(COMBAT, 6, 6, 3, foe_weapon_skill=4, armour_value=5, automatic_hit=True))


@pytest.mark.parametrize(
    ("printed", "plain", "foe_lost", "stomper_lost"),
    [
        pytest.param(
            Scenario(
                Kind.FIGHT,
                FROSTHEART,
                Side("elven-spearmen", 10, "Thrusting Spear", frontage=1),
                first_round=False,
            ),
            Scenario(
                Kind.FIGHT,
                replace(FROSTHEART, dropped=frozenset({"stomp-attacks"})),
                Side("elven-spearmen", 10, "Thrusting Spear", frontage=1),
                first_round=False,
            ),
            (
                casualties([CLAWS] * 4 + [STOMP] * 2, models=10, wounds=1),
                casualties([CLAWS] * 4, models=10, wounds=1),
            ),
            ({0: Fraction(1)}, {0: Fraction(1)}),
            id="frostheart-outlasts-the-blows",
        ),
        pytest.param(
            Scenario(
                Kind.FIGHT,
                replace(DUEL, rules=(Ref("stomp-attacks", 2),)),
                DUEL,
                first_round=False,
            ),
            Scenario(Kind.FIGHT, DUEL, DUEL, first_round=False),
            (_once(FELLS + (1 - FELLS) ** 2 * (1 - (1 - HIT_FELLS) ** 2)), _once(FELLS)),
            (_once(FELLS), _once(FELLS)),
            id="a-slain-stomper-never-stomps",
        ),
    ],
)
def test_stomp_attacks(
    printed: Scenario,
    plain: Scenario,
    foe_lost: tuple[dict[int, Fraction], dict[int, Fraction]],
    stomper_lost: tuple[dict[int, Fraction], dict[int, Fraction]],
) -> None:
    """After every blow, each stomper still standing makes X automatic hits at its Strength.

    The Frostheart's two S6 stomps follow its four claws: two Spearmen and a spear
    behind them cannot take its five Wounds. A stomping spearman trading blows with
    another at equal Initiative stomps twice only if the foe's blow spared it, and
    only at a foe its own blow spared.
    """
    with_rule, without = resolve(printed), resolve(plain)
    assert (with_rule.casualties, without.casualties) == foe_lost
    assert (with_rule.attacker_casualties, without.attacker_casualties) == stomper_lost


def test_blizzard_aura() -> None:
    """Spearmen engaged with the Frostheart Phoenix strike at Initiative 1, after its I3."""
    scenario = Scenario(Kind.STRIKE, FROSTHEART, SPEARMEN)
    printed = resolve(scenario)
    plain = resolve(scenario.without("blizzard-aura", Role.ATTACKER))
    assert (printed.initiative[Role.ATTACKER], printed.initiative[Role.DEFENDER]) == (3, 1)
    assert (plain.initiative[Role.ATTACKER], plain.initiative[Role.DEFENDER]) == (3, 4)


@pytest.mark.parametrize(
    ("first_round", "printed"),
    [pytest.param(True, 5, id="first-round"), pytest.param(False, 4, id="later-round")],
)
def test_elven_reflexes(first_round: bool, printed: int) -> None:
    """Spearmen fight the first round of a combat at Initiative 5, not 4."""
    swords = Side("elven-spearmen", 10, "Hand Weapon")
    scenario = Scenario(Kind.STRIKE, swords, DWARFS, first_round=first_round)
    assert (
        resolve(scenario).initiative[Role.ATTACKER],
        resolve(scenario.without("elven-reflexes", Role.ATTACKER)).initiative[Role.ATTACKER],
    ) == (printed, 4)


def test_strike_first() -> None:
    """Sisters strike at Initiative 10, before I6 Swordmasters who would otherwise go first.

    Handed Strike Last by the Frostheart's aura, the two cancel and the Sisters
    keep their printed Initiative 5.
    """
    scenario = Scenario(
        Kind.STRIKE,
        Side("sisters-of-avelorn", 10, "Hand Weapon"),
        Side("swordmasters-of-hoeth", 10, "Hand Weapon"),
    )
    printed = resolve(scenario)
    plain = resolve(scenario.without("strike-first", Role.ATTACKER))
    assert (printed.initiative[Role.ATTACKER], printed.initiative[Role.DEFENDER]) == (10, 6)
    assert (plain.initiative[Role.ATTACKER], plain.initiative[Role.DEFENDER]) == (5, 6)
    aura = Scenario(Kind.STRIKE, Side("sisters-of-avelorn", 10, "Hand Weapon"), FROSTHEART)
    last = aura.without("strike-first", Role.ATTACKER)
    assert [resolve(each).initiative[Role.ATTACKER] for each in (aura, last)] == [5, 1]


@pytest.mark.parametrize(
    ("charged", "first_round", "printed", "plain"),
    [
        pytest.param(
            None,
            False,
            (1, 4),
            (5, 4),
            id="standing",
        ),
        pytest.param(
            2,
            True,
            (1 + 2 + 1, 5),
            (5 + 2 + 1, 5),
            id="charged-2-inches",
            marks=pytest.mark.xfail(
                strict=True,
                reason="Strike Last's charged case needs the charge's Initiative bonus",
            ),
        ),
    ],
)
def test_strike_last(
    charged: int | None,
    first_round: bool,
    printed: tuple[int, int],
    plain: tuple[int, int],
) -> None:
    """White Lions swinging great blades strike at Initiative 1, after I4 Spearmen.

    The 1 comes before any other modifier: a 2" charge and Elven Reflexes lift it to
    4, still behind the Spearmen's 5 in the first round.
    """
    lions = Side("white-lions-of-chrace", 10, "Chracian Great Blade", charged=charged)
    scenario = Scenario(Kind.STRIKE, lions, SPEARMEN, first_round=first_round)
    with_rule = resolve(scenario)
    without = resolve(scenario.without("strike-last", Role.ATTACKER))
    assert (with_rule.initiative[Role.ATTACKER], with_rule.initiative[Role.DEFENDER]) == printed
    assert (without.initiative[Role.ATTACKER], without.initiative[Role.DEFENDER]) == plain
