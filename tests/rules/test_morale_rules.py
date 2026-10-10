"""Each rule that changes combat result, Break tests or Panic tests, with and without it."""

from collections.abc import Callable, Mapping
from dataclasses import replace
from fractions import Fraction

import pytest
from oracle.procedure import (
    Attack,
    Phase,
    break_test,
    casualties,
    exchange,
    leadership_test,
    one_attack,
)

from avelorn.core.distribution import Probability
from rules.scenario import Break, Kind, Outcome, Panic, Role, Scenario, Side, resolve

SPEARMEN = Side("elven-spearmen", 10, "Thrusting Spear")
ARCHERS = Side("elven-archers", 10, frontage=10)
CHARGING = Side("elven-spearmen", 10, "Hand Weapon", charged=5)
WALL = Side("elven-spearmen", 15, "Thrusting Spear")


def _break_test_rolled(outcome: Outcome, loser: Role, leadership: int) -> Break:
    sign = 1 if loser is Role.DEFENDER else -1
    lost: Mapping[int, Probability] = {
        sign * lead: p for lead, p in outcome.margin.items() if sign * lead > 0
    }
    rolls = {by: break_test(leadership, by) for by in lost}
    return Break(
        sum(p * rolls[by].gives_ground for by, p in lost.items()),
        sum(p * rolls[by].falls_back for by, p in lost.items()),
        sum(p * rolls[by].breaks for by, p in lost.items()),
    )


def _breaks(outcome: Outcome, side: Role) -> Break:
    return outcome.breaks[side]


def _results(outcome: Outcome, side: Role) -> Break:
    return outcome.results[side]


def _failed(panic: Panic | None) -> Probability:
    assert panic is not None
    return panic.falls_back + panic.flees


def _sign(lead: int) -> int:
    return (lead > 0) - (lead < 0)


def _tested(attack: Attack, shots: int, models: int) -> Fraction:
    lost = casualties([one_attack(attack)] * shots, models=models, wounds=1)
    return sum((p for k, p in lost.items() if 4 * k > models and k < models), Fraction(0))


EQUAL_RANKS = Scenario(
    Kind.FIGHT,
    Side("elven-spearmen", 10, "Hand Weapon", frontage=10),
    Side("dwarf-warriors", 10, "Hand Weapon", frontage=10),
    first_round=False,
)
EQUAL_RANKS_TRADED = exchange(
    one_attack(Attack(Phase.COMBAT, 4, 3, 4, foe_weapon_skill=4, armour_value=5)),
    one_attack(Attack(Phase.COMBAT, 4, 3, 3, foe_weapon_skill=4, armour_value=4)),
    models=10,
)


def _after_the_round(_: Mapping[int, Probability]) -> dict[int, Fraction]:
    margin: dict[int, Fraction] = {}
    for (felled, lost), p in EQUAL_RANKS_TRADED.items():
        lead = felled - lost
        margin[lead + _sign(lead)] = margin.get(lead + _sign(lead), Fraction(0)) + p
    return margin


def _one_more(plain: Mapping[int, Probability]) -> dict[int, Probability]:
    return {lead + 1: p for lead, p in plain.items()}


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        pytest.param(
            Scenario(
                Kind.FIGHT,
                replace(SPEARMEN, models=21, frontage=5),
                Side("dwarf-warriors", 10, "Hand Weapon", frontage=5),
                first_round=False,
            ),
            _one_more,
            id="outnumbering-whatever-falls",
        ),
        pytest.param(EQUAL_RANKS, _after_the_round, id="equal-unit-strength"),
    ],
)
def test_massed_infantry(
    scenario: Scenario,
    expected: Callable[[Mapping[int, Probability]], Mapping[int, Probability]],
) -> None:
    """The side with the higher Unit Strength once the blows have landed claims +1.

    21 Spearmen against 10 Dwarfs outnumber however the round goes. Ten a side in one
    rank, the round's casualties decide it: the plain margin is the difference in
    models slain, and whoever slew more claims the bonus.
    """
    plain = scenario.without("massed-infantry", Role.ATTACKER).without(
        "massed-infantry", Role.DEFENDER
    )
    assert resolve(scenario).margin == expected(resolve(plain).margin)


@pytest.mark.parametrize(
    ("printed", "plain", "leadership", "walled"),
    [
        pytest.param(
            Scenario(Kind.BREAK, CHARGING, WALL, first_round=True).adding(
                "shieldwall", Role.DEFENDER
            ),
            Scenario(Kind.BREAK, CHARGING, WALL, first_round=True),
            8,
            True,
            id="charged",
        ),
        pytest.param(
            Scenario(Kind.BREAK, replace(CHARGING, charged=None), WALL, first_round=False).adding(
                "shieldwall", Role.DEFENDER
            ),
            Scenario(Kind.BREAK, replace(CHARGING, charged=None), WALL, first_round=False),
            8,
            False,
            id="not-charged",
        ),
        pytest.param(
            Scenario(
                Kind.BREAK, CHARGING, Side("dwarf-warriors", 10, "Hand Weapon"), first_round=True
            ),
            Scenario(
                Kind.BREAK, CHARGING, Side("dwarf-warriors", 10, "Hand Weapon"), first_round=True
            ).without("shieldwall", Role.DEFENDER),
            9,
            False,
            id="charged-without-a-shield",
        ),
        pytest.param(
            Scenario(
                Kind.BREAK, CHARGING, replace(WALL, used=("shieldwall",)), first_round=True
            ).adding("shieldwall", Role.DEFENDER),
            Scenario(Kind.BREAK, CHARGING, replace(WALL, used=("shieldwall",)), first_round=True),
            8,
            False,
            id="used-this-game",
        ),
    ],
)
def test_shieldwall(printed: Scenario, plain: Scenario, leadership: int, walled: bool) -> None:
    """A shielded unit charged this turn Gives Ground where it would Fall Back in Good Order.

    Once a game: a wall used before falls back.

    Ten Elves cannot wipe out fifteen Spearmen in a round, so a beaten wall
    always takes its test.
    """
    with_rule, without = resolve(printed), resolve(plain)
    rolled = _break_test_rolled(with_rule, Role.DEFENDER, leadership)
    wall = Break(rolled.gives_ground + rolled.falls_back, 0, rolled.breaks)
    assert with_rule.margin == without.margin
    assert (_results(with_rule, Role.DEFENDER), _results(without, Role.DEFENDER)) == (
        wall if walled else rolled,
        _break_test_rolled(without, Role.DEFENDER, leadership),
    )


@pytest.mark.parametrize(
    ("spearmen", "ironbreakers", "overwhelmed"),
    [
        pytest.param(
            replace(SPEARMEN, models=5, frontage=5),
            Side("ironbreakers", 10, "Hand Weapon"),
            False,
            id="first-break-test",
        ),
        pytest.param(
            Side("elven-spearmen", 19, "Thrusting Spear", frontage=2),
            Side("ironbreakers", 7, "Hand Weapon", frontage=2),
            True,
            id="outnumbered-more-than-twice",
        ),
    ],
)
def test_stubborn(spearmen: Side, ironbreakers: Side, overwhelmed: bool) -> None:
    """Ironbreakers that lose Fall Back in Good Order instead of taking the Break test.

    They fall back even from Spearmen over twice their Unit Strength, who would
    turn a rolled fall back into a Break. Neither side can wipe out the other in
    a round, so beaten Ironbreakers always face the test.
    """
    scenario = Scenario(Kind.BREAK, spearmen, ironbreakers, first_round=False)
    printed = resolve(scenario)
    plain = resolve(scenario.without("stubborn", Role.DEFENDER))
    lost = sum(p for lead, p in printed.margin.items() if lead > 0)
    rolled = _break_test_rolled(plain, Role.DEFENDER, 9)
    if overwhelmed:
        rolled = Break(rolled.gives_ground, 0, rolled.falls_back + rolled.breaks)
    assert printed.margin == plain.margin
    assert (_results(printed, Role.DEFENDER), _results(plain, Role.DEFENDER)) == (
        Break(0, lost, 0),
        rolled,
    )


def test_terror() -> None:
    """Spearmen beaten by the Merwyrm test at Leadership 7; the Merwyrm, beaten, keeps its 8.

    Neither five Spearmen nor the Merwyrm's four blows can wipe out the other in
    a round, so the loser always tests.
    """
    scenario = Scenario(
        Kind.BREAK,
        Side("merwyrm", 1, "Lashing Talons"),
        replace(SPEARMEN, models=5, frontage=5),
        first_round=False,
    )
    printed = resolve(scenario)
    plain = resolve(scenario.without("terror", Role.ATTACKER))
    assert printed.margin == plain.margin
    assert (_breaks(printed, Role.DEFENDER), _breaks(plain, Role.DEFENDER)) == (
        _break_test_rolled(printed, Role.DEFENDER, 7),
        _break_test_rolled(plain, Role.DEFENDER, 8),
    )
    assert _breaks(printed, Role.ATTACKER) == _break_test_rolled(printed, Role.ATTACKER, 8)


ARROWS_AT_SPEARMEN = Attack(Phase.SHOOTING, 4, 3, 3, armour_value=5, armour_bane=1)
ARROWS_AT_LONGBEARDS = Attack(Phase.SHOOTING, 4, 3, 4, armour_value=5, armour_bane=1)


def test_valour_of_ages() -> None:
    """Spearmen re-roll a failed Panic test from heavy casualties, failing only twice running.

    Four Spearmen under ten arrows test when more than one but not all of them fall.
    """
    scenario = Scenario(Kind.PANIC, ARCHERS, replace(SPEARMEN, models=4), distance=10)
    printed = resolve(scenario).panic
    plain = resolve(scenario.without("valour-of-ages", Role.DEFENDER)).panic
    tested = _tested(ARROWS_AT_SPEARMEN, shots=10, models=4)
    assert (_failed(printed), _failed(plain)) == (
        tested * (1 - leadership_test(8, re_roll_failed=True)),
        tested * (1 - leadership_test(8)),
    )


def test_veteran() -> None:
    """Longbeards re-roll a failed Leadership test, so a Panic test fails only twice running.

    Four Longbeards under ten arrows test when more than one but not all of them fall.
    """
    scenario = Scenario(Kind.PANIC, ARCHERS, Side("longbeards", 4), distance=10)
    printed = resolve(scenario).panic
    plain = resolve(scenario.without("veteran", Role.DEFENDER)).panic
    tested = _tested(ARROWS_AT_LONGBEARDS, shots=10, models=4)
    assert (_failed(printed), _failed(plain)) == (
        tested * (1 - leadership_test(9, re_roll_failed=True)),
        tested * (1 - leadership_test(9)),
    )
