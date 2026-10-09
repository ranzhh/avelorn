"""Each rule that changes a volley, shot with and without it."""

from dataclasses import replace
from fractions import Fraction

import pytest
from oracle.procedure import Attack, Phase, ReRoll, one_attack

from rules.scenario import Kind, Ref, Role, Scenario, Side, resolve

SHOOTING = Phase.SHOOTING
SHORT, LONG = 10, 20
ARCHERS = Side("elven-archers", 5, frontage=5)
SISTERS = Side("sisters-of-avelorn", 5, frontage=5)
SPEARMEN = Side("elven-spearmen", 10)
ARCHERS_AT_SPEARMEN = Attack(SHOOTING, 4, 3, 3, armour_value=5, armour_bane=1)


def _unsaved(attack: Attack) -> Fraction:
    return one_attack(attack).unsaved


def _with_and_without(printed: Scenario, plain: Scenario) -> tuple[object, object]:
    return resolve(printed).unsaved, resolve(plain).unsaved


@pytest.mark.parametrize(
    ("distance", "printed", "plain"),
    [pytest.param(LONG, -2, -1, id="long-range"), pytest.param(SHORT, 0, 0, id="short-range")],
)
def test_abyssal_cloak(distance: int, printed: int, plain: int) -> None:
    """Long-range shots at the Merwyrm are -2 To Hit rather than -1; short ones are untouched."""
    scenario = Scenario(Kind.SHOOT, ARCHERS, Side("merwyrm", 1), distance=distance)
    longbow = Attack(SHOOTING, 4, 3, 6, armour_value=5, armour_bane=1)
    assert _with_and_without(scenario, scenario.without("abyssal-cloak", Role.DEFENDER)) == (
        _unsaved(replace(longbow, hit_modifier=printed)),
        _unsaved(replace(longbow, hit_modifier=plain)),
    )


def test_armour_bane() -> None:
    """The longbow's Armour Bane (1) adds AP -1 to a shot whose wound roll is a natural 6."""
    scenario = Scenario(Kind.SHOOT, ARCHERS, SPEARMEN, distance=SHORT)
    assert _with_and_without(scenario, scenario.without("armour-bane", Role.ATTACKER)) == (
        _unsaved(ARCHERS_AT_SPEARMEN),
        _unsaved(replace(ARCHERS_AT_SPEARMEN, armour_bane=0)),
    )


def test_arrows_of_isha() -> None:
    """The Sisters' bow gains AP -1 and a second Armour Bane (1), stacking to Armour Bane (2).

    Source: special-rules/cumulative-special-rules.
    """
    scenario = Scenario(Kind.SHOOT, SISTERS, SPEARMEN, distance=SHORT)
    bow = Attack(SHOOTING, 5, 3, 3, armour_value=5, armour_bane=1)
    assert _with_and_without(scenario, scenario.without("arrows-of-isha", Role.ATTACKER)) == (
        _unsaved(replace(bow, armour_piercing=-1, armour_bane=2)),
        _unsaved(bow),
    )


SWORDMASTERS = Side("swordmasters-of-hoeth", 10, "Hand Weapon")
SISTERS_BOW = Attack(SHOOTING, 5, 3, 3, armour_value=5, armour_piercing=-1, armour_bane=2)
SPEARS_INTO_SWORDMASTERS = Attack(Phase.COMBAT, 4, 3, 3, foe_weapon_skill=6, armour_value=5)


@pytest.mark.parametrize(
    ("scenario", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.SHOOT, ARCHERS, SWORDMASTERS, distance=SHORT),
            replace(ARCHERS_AT_SPEARMEN, ward=6),
            ARCHERS_AT_SPEARMEN,
            id="mundane-longbow",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, SISTERS, SWORDMASTERS, distance=SHORT),
            SISTERS_BOW,
            SISTERS_BOW,
            id="magical-bow",
        ),
        pytest.param(
            Scenario(Kind.STRIKE, Side("elven-spearmen", 5, "Thrusting Spear"), SWORDMASTERS),
            SPEARS_INTO_SWORDMASTERS,
            SPEARS_INTO_SWORDMASTERS,
            id="close-combat",
        ),
    ],
)
def test_deflect_shots(scenario: Scenario, printed: Attack, plain: Attack) -> None:
    """Swordmasters take a 6+ ward against a non-magical shooting attack only."""
    assert _with_and_without(scenario, scenario.without("deflect-shots", Role.DEFENDER)) == (
        _unsaved(printed),
        _unsaved(plain),
    )


SPEARS_INTO_SPEARMEN = Attack(Phase.COMBAT, 4, 3, 3, foe_weapon_skill=4, armour_value=5)


@pytest.mark.parametrize(
    ("scenario", "role", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.SHOOT, ARCHERS, SPEARMEN, distance=SHORT),
            Role.DEFENDER,
            replace(ARCHERS_AT_SPEARMEN, hit_modifier=-1),
            ARCHERS_AT_SPEARMEN,
            id="shot-at",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, ARCHERS, SPEARMEN, distance=SHORT),
            Role.ATTACKER,
            ARCHERS_AT_SPEARMEN,
            ARCHERS_AT_SPEARMEN,
            id="shooting",
        ),
        pytest.param(
            Scenario(
                Kind.STRIKE,
                Side("elven-spearmen", 5, "Thrusting Spear"),
                replace(SPEARMEN, weapon="Thrusting Spear"),
            ),
            Role.DEFENDER,
            SPEARS_INTO_SPEARMEN,
            SPEARS_INTO_SPEARMEN,
            id="struck",
        ),
    ],
)
def test_enemy_fire_skirmishers(
    scenario: Scenario, role: Role, printed: Attack, plain: Attack
) -> None:
    """Shooting at the bearer is -1 To Hit; its own shots and blows struck at it are not."""
    with_rule = scenario.adding("enemy-fire-skirmishers", role)
    assert _with_and_without(with_rule, scenario) == (_unsaved(printed), _unsaved(plain))


@pytest.mark.parametrize(
    ("distance", "printed"),
    [pytest.param(LONG, -1, id="long-range"), pytest.param(SHORT, 0, id="short-range")],
)
def test_firing_at_long_range(distance: int, printed: int) -> None:
    """A shot beyond half the longbow's 30" range is -1 To Hit; one within it is not."""
    scenario = Scenario(Kind.SHOOT, ARCHERS, SPEARMEN, distance=distance)
    assert _with_and_without(scenario, scenario.without("firing-at-long-range")) == (
        _unsaved(replace(ARCHERS_AT_SPEARMEN, hit_modifier=printed)),
        _unsaved(ARCHERS_AT_SPEARMEN),
    )


LIONS = Side("white-lions-of-chrace", 10, "Hand Weapon")
SPEARS_INTO_LIONS = Attack(Phase.COMBAT, 4, 3, 3, foe_weapon_skill=5, armour_value=5)


@pytest.mark.parametrize(
    ("scenario", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.SHOOT, ARCHERS, LIONS, distance=SHORT),
            replace(ARCHERS_AT_SPEARMEN, armour_value=4),
            ARCHERS_AT_SPEARMEN,
            id="mundane-longbow",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, SISTERS, LIONS, distance=SHORT),
            SISTERS_BOW,
            SISTERS_BOW,
            id="magical-bow",
        ),
        pytest.param(
            Scenario(
                Kind.SHOOT,
                ARCHERS,
                Side("dragon-princes", 5, rules=(Ref("lion-cloak"),)),
                distance=SHORT,
            ),
            replace(ARCHERS_AT_SPEARMEN, armour_value=2, ward=6),
            replace(ARCHERS_AT_SPEARMEN, armour_value=2, ward=6),
            id="capped-at-2+",
        ),
        pytest.param(
            Scenario(Kind.STRIKE, Side("elven-spearmen", 5, "Thrusting Spear"), LIONS),
            SPEARS_INTO_LIONS,
            SPEARS_INTO_LIONS,
            id="struck",
        ),
    ],
)
def test_lion_cloak(scenario: Scenario, printed: Attack, plain: Attack) -> None:
    """Against non-magical shooting the save is 1 better, to no better than 2+."""
    assert _with_and_without(scenario, scenario.without("lion-cloak", Role.DEFENDER)) == (
        _unsaved(printed),
        _unsaved(plain),
    )


SISTERS_INTO_IRONBREAKERS = Attack(
    SHOOTING,
    5,
    3,
    4,
    armour_value=3,
    armour_piercing=-1,
    armour_bane=2,
    save_re_rolls=frozenset({ReRoll.ONES}),
)
SPEARS_INTO_IRONBREAKERS = Attack(
    Phase.COMBAT,
    4,
    3,
    4,
    foe_weapon_skill=5,
    armour_value=3,
    save_re_rolls=frozenset({ReRoll.ONES}),
)
IRONBREAKERS = Side("ironbreakers", 10, "Hand Weapon")
ENCHANTED_SPEARS = Scenario(
    Kind.STRIKE, Side("elven-spearmen", 5, "Thrusting Spear", frontage=5), IRONBREAKERS
)


@pytest.mark.parametrize(
    ("printed", "plain", "printed_attack", "plain_attack"),
    [
        pytest.param(
            Scenario(Kind.SHOOT, SISTERS, IRONBREAKERS, distance=SHORT),
            Scenario(Kind.SHOOT, SISTERS, IRONBREAKERS, distance=SHORT).without(
                "magical-attacks", Role.ATTACKER
            ),
            SISTERS_INTO_IRONBREAKERS,
            replace(SISTERS_INTO_IRONBREAKERS, ward=6),
            id="printed-on-the-bow",
        ),
        pytest.param(
            ENCHANTED_SPEARS.adding("magical-attacks", Role.ATTACKER),
            ENCHANTED_SPEARS,
            SPEARS_INTO_IRONBREAKERS,
            replace(SPEARS_INTO_IRONBREAKERS, ward=6),
            id="printed-on-the-unit",
        ),
    ],
)
def test_magical_attacks(
    printed: Scenario, plain: Scenario, printed_attack: Attack, plain_attack: Attack
) -> None:
    """Magical attacks, from a weapon or from the unit, deny the Runes of Protection ward."""
    assert _with_and_without(printed, plain) == (
        _unsaved(printed_attack),
        _unsaved(plain_attack),
    )


@pytest.mark.parametrize(
    ("moved", "printed"),
    [pytest.param(True, -1, id="moved"), pytest.param(False, 0, id="stationary")],
)
def test_moving_and_shooting(moved: bool, printed: int) -> None:
    """Shooters that moved this turn are -1 To Hit."""
    scenario = Scenario(Kind.SHOOT, replace(ARCHERS, moved=moved), SPEARMEN, distance=SHORT)
    assert _with_and_without(scenario, scenario.without("moving-and-shooting")) == (
        _unsaved(replace(ARCHERS_AT_SPEARMEN, hit_modifier=printed)),
        _unsaved(ARCHERS_AT_SPEARMEN),
    )


def test_skirmish_formation() -> None:
    """The formation grants Enemy Fire (Skirmishers): shooting at it is -1 To Hit."""
    scenario = Scenario(Kind.SHOOT, ARCHERS, SPEARMEN, distance=SHORT)
    with_rule = scenario.adding("skirmish-formation", Role.DEFENDER)
    assert _with_and_without(with_rule, scenario) == (
        _unsaved(replace(ARCHERS_AT_SPEARMEN, hit_modifier=-1)),
        _unsaved(ARCHERS_AT_SPEARMEN),
    )


def test_skirmishers() -> None:
    """Shadow Warriors are Skirmishers, so shooting at them is -1 To Hit."""
    scenario = Scenario(Kind.SHOOT, ARCHERS, Side("shadow-warriors", 10), distance=SHORT)
    longbow = Attack(SHOOTING, 4, 3, 3, armour_value=6, armour_bane=1)
    assert _with_and_without(scenario, scenario.without("skirmishers", Role.DEFENDER)) == (
        _unsaved(replace(longbow, hit_modifier=-1)),
        _unsaved(longbow),
    )


DEEP_ARCHERS = Side("elven-archers", 15, frontage=5)
CHARGING_SPEARMEN = Side("elven-spearmen", 10, "Hand Weapon", charged=5)


@pytest.mark.parametrize(
    ("scenario", "printed"),
    [
        pytest.param(
            Scenario(Kind.SHOOT, DEEP_ARCHERS, SPEARMEN, distance=SHORT),
            5 + 3 + 3,
            id="stationary",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, replace(DEEP_ARCHERS, moved=True), SPEARMEN, SHORT),
            5,
            id="moved",
        ),
        pytest.param(
            Scenario(
                Kind.STAND_AND_SHOOT,
                CHARGING_SPEARMEN,
                DEEP_ARCHERS,
            ),
            5,
            id="stand-and-shoot",
        ),
    ],
)
def test_volley_fire(scenario: Scenario, printed: int) -> None:
    """Three ranks of five: half of each rear rank, rounding up, joins the front rank's shots.

    Never after moving, and never on a Stand & Shoot.
    """
    role = Role.DEFENDER if scenario.kind is Kind.STAND_AND_SHOOT else Role.ATTACKER
    plain = scenario.without("volley-fire", role)
    assert (resolve(scenario).attacks, resolve(plain).attacks) == (printed, 5)


def test_standing_and_shooting() -> None:
    """Archers making a Stand & Shoot reaction to charging Spearmen shoot at -1 To Hit.

    The volley is shot as the chargers close, at no range and no long range penalty.
    """
    scenario = Scenario(Kind.STAND_AND_SHOOT, CHARGING_SPEARMEN, ARCHERS)
    assert _with_and_without(scenario, scenario.without("standing-and-shooting")) == (
        _unsaved(replace(ARCHERS_AT_SPEARMEN, hit_modifier=-1)),
        _unsaved(ARCHERS_AT_SPEARMEN),
    )
