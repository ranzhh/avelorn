"""Legacy's attack walk against the oracle of the printed procedure.

Each per-attack figure must match exactly.
"""

import itertools
from collections.abc import Callable

import pytest

from avelorn.core.distribution import Probability
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.charts import melee_hit_target, shooting_hit_target, wound_target
from avelorn.tow.phases.combat import strike, strike_unit
from avelorn.tow.phases.shooting import shoot, shoot_unit
from avelorn.tow.schema.unit import Unit

from .procedure import (
    NO_ARMOUR,
    SHOOTING_TO_HIT,
    Attack,
    Phase,
    ReRoll,
    combat_to_hit,
    one_attack,
    to_wound,
)

REPO = TOWRepository()
SHOOTING, COMBAT = Phase.SHOOTING, Phase.COMBAT
ONES, SUCCESSES = frozenset({ReRoll.ONES}), frozenset({ReRoll.SUCCESSFUL})


def _fielded(unit: str | Unit, models: int, weapon: str | None = None) -> Contingent:
    unit = REPO.units[unit] if isinstance(unit, str) else unit
    contingent = Contingent.field(unit, models, data=REPO)
    return contingent.wielding(weapon) if weapon else contingent


def _with(slug: str, *, rule: str | None = None, equipment: str | None = None) -> Unit:
    unit = REPO.units[slug]
    return unit.model_copy(
        update={
            "special_rules": [*unit.special_rules, *([rule] if rule else [])],
            "equipment": [*unit.equipment, *([equipment] if equipment else [])],
        }
    )


def test_the_charts_match_the_printed_tables() -> None:
    """Every printed cell of the To Hit tables and the To Wound chart."""
    for skill in SHOOTING_TO_HIT:
        assert shooting_hit_target(skill) == SHOOTING_TO_HIT[skill]
    for row, column in itertools.product(range(1, 11), repeat=2):
        assert melee_hit_target(row, column) == combat_to_hit(row, column)
        assert wound_target(row, column) == to_wound(row, column)


@pytest.mark.xfail(
    strict=True,
    reason="legacy reads BS6 as 1+ (5/6); the-shooting-phase/bs-of-6-or-higher prints 2+/6+",
)
def test_ballistic_skill_six_hits_as_printed() -> None:
    """BS6 hits on 2+ and re-rolls a miss at 6+: 31/36 of shots hit."""
    legacy = shoot(1, ballistic_skill=6, strength=10, toughness=1).p_unsaved
    assert legacy == one_attack(Attack(SHOOTING, skill=6, strength=10, toughness=1)).unsaved


def _legacy_volley(attack: Attack) -> Probability:
    armour = None if attack.armour_value == NO_ARMOUR else attack.armour_value
    return shoot(
        1,
        attack.skill,
        attack.strength,
        attack.toughness,
        armour_value=armour,
        armour_piercing=attack.armour_piercing,
        ward_target=attack.ward,
        hit_modifier=attack.hit_modifier,
    ).p_unsaved


def _legacy_strike(attack: Attack) -> Probability:
    assert attack.foe_weapon_skill is not None
    armour = None if attack.armour_value == NO_ARMOUR else attack.armour_value
    return strike(
        1,
        attack.skill,
        attack.foe_weapon_skill,
        attack.strength,
        attack.toughness,
        armour_value=armour,
        armour_piercing=attack.armour_piercing,
        ward_target=attack.ward,
        hit_modifier=attack.hit_modifier,
    ).p_unsaved


@pytest.mark.parametrize(
    "attack",
    [
        pytest.param(Attack(SHOOTING, 4, 3, 3, armour_value=5), id="shoot-golden-chain"),
        pytest.param(Attack(SHOOTING, 4, 3, 3, ward=4), id="shoot-ward-save"),
        pytest.param(Attack(SHOOTING, 5, 1, 7), id="shoot-impossible-wound"),
        pytest.param(Attack(COMBAT, 4, 4, 4, foe_weapon_skill=4), id="strike-golden-no-save"),
        pytest.param(
            Attack(COMBAT, 6, 5, 3, foe_weapon_skill=3, armour_value=5),
            id="strike-golden-with-armour",
        ),
        pytest.param(
            Attack(COMBAT, 4, 10, 1, foe_weapon_skill=4, hit_modifier=-3),
            id="strike-hit-penalty-past-the-chart",
        ),
    ],
)
def test_plain_dice_scenarios_match(attack: Attack) -> None:
    """The legacy tests' shoot() and strike() scenarios, attack by attack."""
    legacy = _legacy_volley(attack) if attack.phase is SHOOTING else _legacy_strike(attack)
    assert legacy == one_attack(attack).unsaved


def test_every_plain_dice_combination_matches() -> None:
    """A sweep over skills, modifiers past the 7+ table, armour, AP and wards."""
    volleys = [
        Attack(SHOOTING, bs, s, t, hit_modifier=hm, armour_value=av, armour_piercing=ap, ward=w)
        for bs, hm, (s, t), av, ap, w in itertools.product(
            range(1, 6), range(-5, 2), [(3, 3), (2, 7), (6, 3)], range(2, 8), [0, -2], [None, 5]
        )
    ]
    strikes = [
        Attack(COMBAT, ws, 4, 4, foe_weapon_skill=fws, hit_modifier=hm, armour_value=av)
        for ws, fws, hm, av in itertools.product(range(1, 11), range(1, 11), [-3, 0, 2], [4, 7])
    ]
    pairs = [(a, _legacy_volley(a)) for a in volleys] + [(a, _legacy_strike(a)) for a in strikes]
    disputes = [(a, legacy, one_attack(a).unsaved) for a, legacy in pairs]
    assert [dispute for dispute in disputes if dispute[1] != dispute[2]] == []


# Legacy fields each side from the data; the oracle reads the printed datasheets:
# BS4 archers' longbow S3 Armour Bane (1); spearmen T3 WS4, light armour and shield 5+;
# Ironbreakers T4 WS5, full plate and shield 3+, Gromril Armour, Runes of Protection 6+.
FIELDED: list[tuple[str, Callable[[], Probability], Attack]] = [
    (
        "archers-v-spearmen",
        lambda: (
            shoot_unit(
                _fielded("elven-archers", 3, "Longbow"), _fielded("elven-spearmen", 10)
            ).p_unsaved
        ),
        Attack(SHOOTING, 4, 3, 3, armour_value=5, armour_bane=1),
    ),
    (
        "sea-guard-warbow-v-spearmen",
        lambda: (
            shoot_unit(
                _fielded("lothern-sea-guard", 3, "Warbow"), _fielded("elven-spearmen", 10)
            ).p_unsaved
        ),
        Attack(SHOOTING, 4, 3, 3, armour_value=5),
    ),
    (
        "archers-v-ironbreakers-gromril-save-re-roll",
        lambda: (
            shoot_unit(
                _fielded("elven-archers", 5, "Longbow"), _fielded("ironbreakers", 10)
            ).p_unsaved
        ),
        Attack(SHOOTING, 4, 3, 4, armour_value=3, armour_bane=1, ward=6, save_re_rolls=ONES),
    ),
    (
        # Lion Cloak betters heavy armour's 5+ to 4+ against a mundane shot.
        "archers-v-white-lions",
        lambda: (
            shoot_unit(
                _fielded("elven-archers", 5, "Longbow"), _fielded("white-lions-of-chrace", 10)
            ).p_unsaved
        ),
        Attack(SHOOTING, 4, 3, 3, armour_value=4, armour_bane=1),
    ),
    (
        # The magical Bow of Avelorn: no Lion Cloak, and Arrows of Isha's AP -1.
        "sisters-v-white-lions",
        lambda: (
            shoot_unit(
                _fielded("sisters-of-avelorn", 5, "Bow of Avelorn"),
                _fielded("white-lions-of-chrace", 10),
                force_short_range=True,
            ).p_unsaved
        ),
        Attack(SHOOTING, 5, 3, 3, armour_value=5, armour_piercing=-1, armour_bane=1),
    ),
    (
        # Enemy Fire (Skirmishers): -1 To Hit; light armour 6+.
        "archers-v-shadow-warriors",
        lambda: (
            shoot_unit(
                _fielded("elven-archers", 5, "Longbow"), _fielded("shadow-warriors", 10)
            ).p_unsaved
        ),
        Attack(SHOOTING, 4, 3, 3, hit_modifier=-1, armour_value=6, armour_bane=1),
    ),
    (
        "spearmen-v-spearmen",
        lambda: (
            strike_unit(
                _fielded("elven-spearmen", 5, "Thrusting Spear"), _fielded("elven-spearmen", 10)
            ).p_unsaved
        ),
        Attack(COMBAT, 4, 3, 3, foe_weapon_skill=4, armour_value=5),
    ),
    (
        # Parry: a hand weapon and shield better the 5+ to 4+.
        "spearmen-v-parrying-spearmen",
        lambda: (
            strike_unit(
                _fielded("elven-spearmen", 5, "Hand Weapon"),
                _fielded("elven-spearmen", 10, "Hand Weapon"),
            ).p_unsaved
        ),
        Attack(COMBAT, 4, 3, 3, foe_weapon_skill=4, armour_value=4),
    ),
    (
        "sisters-ithilmar-weapons-v-spearmen",
        lambda: (
            strike_unit(
                _fielded("sisters-of-avelorn", 5, "Hand Weapon"), _fielded("elven-spearmen", 10)
            ).p_unsaved
        ),
        Attack(COMBAT, 5, 3, 3, foe_weapon_skill=4, armour_value=5, hit_re_rolls=ONES),
    ),
    (
        "spearmen-v-ironbreakers-gromril-save-re-roll",
        lambda: (
            strike_unit(
                _fielded("elven-spearmen", 5, "Thrusting Spear"),
                _fielded("ironbreakers", 10, "Hand Weapon"),
            ).p_unsaved
        ),
        Attack(COMBAT, 4, 3, 4, foe_weapon_skill=5, armour_value=3, ward=6, save_re_rolls=ONES),
    ),
    (
        # Gromril Weapons: AP -1 on the hand weapon.
        "ironbreakers-v-spearmen",
        lambda: (
            strike_unit(
                _fielded("ironbreakers", 5, "Hand Weapon"),
                _fielded("elven-spearmen", 10, "Thrusting Spear"),
            ).p_unsaved
        ),
        Attack(COMBAT, 5, 4, 3, foe_weapon_skill=4, armour_value=5, armour_piercing=-1),
    ),
    (
        # Daith's Reaper: S+1, AP -1, successful saves re-rolled; Dwarf heavy armour 5+.
        "daiths-reaper-v-dwarf-warriors",
        lambda: (
            strike_unit(
                _fielded(_with("elven-spearmen", equipment="Daith's Reaper"), 5, "Daith's Reaper"),
                _fielded("dwarf-warriors", 10, "Hand Weapon"),
            ).p_unsaved
        ),
        Attack(
            COMBAT,
            4,
            4,
            4,
            foe_weapon_skill=4,
            armour_value=5,
            armour_piercing=-1,
            save_re_rolls=SUCCESSES,
        ),
    ),
    (
        "killing-blow-v-spearmen",
        lambda: (
            strike_unit(
                _fielded(_with("elven-spearmen", rule="Killing Blow"), 10, "Hand Weapon"),
                _fielded("elven-spearmen", 10, "Thrusting Spear"),
            ).p_unsaved
        ),
        Attack(COMBAT, 4, 3, 3, foe_weapon_skill=4, armour_value=5, killing_blow=True),
    ),
]


@pytest.mark.parametrize(
    ("legacy", "attack"),
    [pytest.param(legacy, attack, id=name) for name, legacy, attack in FIELDED],
)
def test_fielded_scenarios_match(legacy: Callable[[], Probability], attack: Attack) -> None:
    """The legacy tests' data-driven volleys and strikes, attack by attack."""
    assert legacy() == one_attack(attack).unsaved

