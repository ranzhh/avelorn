"""Each rule that changes one side's blows in close combat, struck with and without it."""

from dataclasses import replace
from fractions import Fraction

import pytest
from oracle.procedure import Attack, Phase, ReRoll, casualties, one_attack

from rules.scenario import Carrier, Kind, Role, Scenario, Side, resolve

COMBAT, SHOOTING = Phase.COMBAT, Phase.SHOOTING
ONES = frozenset({ReRoll.ONES})
SPEARS = Side("elven-spearmen", 5, "Thrusting Spear", frontage=5)
SWORDS = Side("elven-spearmen", 5, "Hand Weapon", frontage=5)
SPEARMEN = Side("elven-spearmen", 10, "Thrusting Spear")
PHOENIX_GUARD = Side("phoenix-guard", 10, "Ceremonial Halberd")
IRONBREAKERS = Side("ironbreakers", 10, "Hand Weapon")
SWORDS_OF_HOETH = Side(
    "swordmasters-of-hoeth",
    5,
    "Sword of Hoeth",
    frontage=5,
    dropped=frozenset({"cleaving-blow"}),
)
FLAMESPYRE = Side("flamespyre-phoenix", 1, "Wicked Claws")
SPEAR_INTO_SPEARMEN = Attack(COMBAT, 4, 3, 3, foe_weapon_skill=4, armour_value=5)
ARCHERS = Side("elven-archers", 5, frontage=5)
ARROWS_INTO_PHOENIX_GUARD = Attack(SHOOTING, 4, 3, 3, armour_value=4, armour_bane=1, ward=6)


def _unsaved(attack: Attack) -> Fraction:
    return one_attack(attack).unsaved


def _with_and_without(printed: Scenario, plain: Scenario) -> tuple[object, object]:
    return resolve(printed).unsaved, resolve(plain).unsaved


@pytest.mark.parametrize(
    ("scenario", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.STRIKE, FLAMESPYRE, PHOENIX_GUARD),
            Attack(
                COMBAT, 5, 5, 3, foe_weapon_skill=5, armour_value=4, armour_piercing=-2, ward=5
            ),
            Attack(
                COMBAT, 5, 5, 3, foe_weapon_skill=5, armour_value=4, armour_piercing=-2, ward=6
            ),
            id="flaming-claws",
        ),
        pytest.param(
            Scenario(Kind.STRIKE, SWORDS, PHOENIX_GUARD),
            Attack(COMBAT, 4, 3, 3, foe_weapon_skill=5, armour_value=4, ward=6),
            Attack(COMBAT, 4, 3, 3, foe_weapon_skill=5, armour_value=4, ward=6),
            id="plain-swords",
        ),
        pytest.param(
            Scenario(
                Kind.SHOOT, replace(ARCHERS, weapon="Longbow"), PHOENIX_GUARD, distance=10
            ).adding("flaming-attacks", Role.ATTACKER, Carrier.WEAPON),
            replace(ARROWS_INTO_PHOENIX_GUARD, ward=5),
            ARROWS_INTO_PHOENIX_GUARD,
            id="flaming-longbow",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, ARCHERS, PHOENIX_GUARD, distance=10),
            ARROWS_INTO_PHOENIX_GUARD,
            ARROWS_INTO_PHOENIX_GUARD,
            id="plain-arrows",
        ),
    ],
)
def test_blessings_of_asuryan(scenario: Scenario, printed: Attack, plain: Attack) -> None:
    """Phoenix Guard ward a Flaming attack, struck or shot, on 5+."""
    assert _with_and_without(
        scenario, scenario.without("blessings-of-asuryan", Role.DEFENDER)
    ) == (_unsaved(printed), _unsaved(plain))


@pytest.mark.parametrize(
    ("target", "printed", "plain"),
    [
        pytest.param(
            SPEARMEN,
            Attack(COMBAT, 6, 3, 3, foe_weapon_skill=4, armour_value=5, cleaving_blow=True),
            Attack(COMBAT, 6, 3, 3, foe_weapon_skill=4, armour_value=5),
            id="regular-infantry",
        ),
        pytest.param(
            Side("maneaters", 3, "Hand Weapon"),
            Attack(COMBAT, 6, 3, 4, foe_weapon_skill=4, armour_value=6),
            Attack(COMBAT, 6, 3, 4, foe_weapon_skill=4, armour_value=6),
            id="monstrous-infantry",
        ),
    ],
)
def test_cleaving_blow(target: Side, printed: Attack, plain: Attack) -> None:
    """A natural 6 To Wound denies the armour save, against the five troop types it names."""
    scenario = Scenario(
        Kind.STRIKE, Side("swordmasters-of-hoeth", 5, "Hand Weapon", frontage=5), target
    )
    assert _with_and_without(scenario, scenario.without("cleaving-blow", Role.ATTACKER)) == (
        _unsaved(printed),
        _unsaved(plain),
    )


@pytest.mark.parametrize(
    ("scenario", "attack"),
    [
        pytest.param(
            Scenario(Kind.STRIKE, SPEARS, Side("dragon-princes", 5, "Hand Weapon")),
            Attack(COMBAT, 4, 3, 3, foe_weapon_skill=5, armour_value=2),
            id="struck",
            marks=pytest.mark.xfail(strict=True, reason="Dragon Armour needs ridden units"),
        ),
        pytest.param(
            Scenario(Kind.SHOOT, ARCHERS, Side("dragon-princes", 5), distance=10),
            Attack(SHOOTING, 4, 3, 3, armour_value=2, armour_bane=1),
            id="shot",
        ),
    ],
)
def test_dragon_armour(scenario: Scenario, attack: Attack) -> None:
    """Dragon Princes take a 6+ ward against every attack."""
    assert _with_and_without(scenario, scenario.without("dragon-armour", Role.DEFENDER)) == (
        _unsaved(replace(attack, ward=6)),
        _unsaved(attack),
    )


def test_enfeebling_cold() -> None:
    """White Lions engaged with the Merwyrm strike at Strength 5 rather than 6."""
    scenario = Scenario(
        Kind.STRIKE,
        Side("white-lions-of-chrace", 5, "Chracian Great Blade", frontage=5),
        Side("merwyrm", 1, "Lashing Talons"),
    )
    blade = Attack(COMBAT, 5, 6, 6, foe_weapon_skill=6, armour_value=5, armour_piercing=-3)
    assert _with_and_without(scenario, scenario.without("enfeebling-cold", Role.DEFENDER)) == (
        _unsaved(replace(blade, strength=5)),
        _unsaved(blade),
    )


def test_flaming_attacks() -> None:
    """The Flamespyre's flaming claws meet Phoenix Guard's 5+ Blessings, not only the 6+ ward."""
    scenario = Scenario(Kind.STRIKE, FLAMESPYRE, PHOENIX_GUARD)
    claws = Attack(COMBAT, 5, 5, 3, foe_weapon_skill=5, armour_value=4, armour_piercing=-2)
    assert _with_and_without(scenario, scenario.without("flaming-attacks", Role.ATTACKER)) == (
        _unsaved(replace(claws, ward=5)),
        _unsaved(replace(claws, ward=6)),
    )


GROMRIL_BLOW = Attack(COMBAT, 4, 3, 4, foe_weapon_skill=5, armour_value=3, ward=6)
GROMRIL_SHOT = Attack(SHOOTING, 4, 3, 4, armour_value=3, armour_bane=1, ward=6)
GROMRIL_SHOT_RE_ROLLED = replace(GROMRIL_SHOT, save_re_rolls=ONES)
IRONBREAKER_BLOW = Attack(COMBAT, 5, 4, 3, foe_weapon_skill=4, armour_value=5, armour_piercing=-1)


@pytest.mark.parametrize(
    ("scenario", "role", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.STRIKE, SPEARS, IRONBREAKERS),
            Role.DEFENDER,
            replace(GROMRIL_BLOW, save_re_rolls=ONES),
            GROMRIL_BLOW,
            id="struck",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, ARCHERS, IRONBREAKERS, distance=10),
            Role.DEFENDER,
            GROMRIL_SHOT_RE_ROLLED,
            GROMRIL_SHOT,
            id="shot",
        ),
        pytest.param(
            Scenario(Kind.STRIKE, replace(IRONBREAKERS, models=5, frontage=5), SPEARMEN),
            Role.ATTACKER,
            IRONBREAKER_BLOW,
            IRONBREAKER_BLOW,
            id="striking",
        ),
    ],
)
def test_gromril_armour(scenario: Scenario, role: Role, printed: Attack, plain: Attack) -> None:
    """Ironbreakers re-roll their own armour saves of a natural 1, never the enemy's."""
    assert _with_and_without(scenario, scenario.without("gromril-armour", role)) == (
        _unsaved(printed),
        _unsaved(plain),
    )


LONGBEARD_GREAT_BLOW = Attack(
    COMBAT,
    5,
    6,
    4,
    foe_weapon_skill=5,
    armour_value=3,
    armour_piercing=-2,
    armour_bane=1,
    ward=6,
    save_re_rolls=ONES,
)


@pytest.mark.parametrize(
    ("scenario", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.STRIKE, replace(IRONBREAKERS, models=5, frontage=5), SPEARMEN),
            replace(IRONBREAKER_BLOW, armour_piercing=-1),
            replace(IRONBREAKER_BLOW, armour_piercing=0),
            id="hand-weapon",
        ),
        pytest.param(
            Scenario(
                Kind.STRIKE,
                Side("longbeards", 5, "Great Weapon", frontage=5, equipment=("Great Weapon",)),
                IRONBREAKERS,
            ),
            LONGBEARD_GREAT_BLOW,
            LONGBEARD_GREAT_BLOW,
            id="great-weapon",
        ),
    ],
)
def test_gromril_weapons(scenario: Scenario, printed: Attack, plain: Attack) -> None:
    """A Dwarf's hand weapon gains AP -1; a great weapon keeps its own AP -2."""
    assert _with_and_without(scenario, scenario.without("gromril-weapons", Role.ATTACKER)) == (
        _unsaved(printed),
        _unsaved(plain),
    )


SISTERS_BLOW = Attack(COMBAT, 5, 3, 3, foe_weapon_skill=4, armour_value=5)
SISTERS_GREAT_BLOW = Attack(
    COMBAT, 5, 5, 3, foe_weapon_skill=4, armour_value=5, armour_piercing=-2, armour_bane=1
)


SISTERS_BOW = Attack(SHOOTING, 5, 3, 3, armour_value=5, armour_piercing=-1, armour_bane=2)


def _sisters(weapon: str) -> Side:
    return Side("sisters-of-avelorn", 5, weapon, frontage=5, equipment=("Great Weapon",))


@pytest.mark.parametrize(
    ("scenario", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.STRIKE, _sisters("Hand Weapon"), SPEARMEN),
            replace(SISTERS_BLOW, hit_re_rolls=ONES),
            SISTERS_BLOW,
            id="hand-weapon",
        ),
        pytest.param(
            Scenario(Kind.STRIKE, _sisters("Great Weapon"), SPEARMEN),
            SISTERS_GREAT_BLOW,
            SISTERS_GREAT_BLOW,
            id="great-weapon",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, _sisters("Bow of Avelorn"), SPEARMEN, distance=10),
            SISTERS_BOW,
            SISTERS_BOW,
            id="shooting",
        ),
    ],
)
def test_ithilmar_weapons(scenario: Scenario, printed: Attack, plain: Attack) -> None:
    """Sisters with hand weapons re-roll To Hit rolls of a natural 1 in combat."""
    assert _with_and_without(scenario, scenario.without("ithilmar-weapons", Role.ATTACKER)) == (
        _unsaved(printed),
        _unsaved(plain),
    )


LONE_SPEARMAN = Side("elven-spearmen", 1, "Hand Weapon", frontage=1)
KILLING_BLOW = Attack(COMBAT, 4, 3, 4, foe_weapon_skill=4, armour_value=6, killing_blow=True)
WARDED_BLOW = Attack(COMBAT, 4, 3, 3, foe_weapon_skill=5, armour_value=4, ward=6)


@pytest.mark.parametrize(
    ("scenario", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.STRIKE, LONE_SPEARMAN, Side("maneaters", 1, "Hand Weapon")),
            one_attack(KILLING_BLOW).kill,
            Fraction(0),
            id="monstrous-infantry",
            marks=pytest.mark.xfail(
                strict=True, reason="Killing Blow needs casualty classes at Remove Casualties"
            ),
        ),
        pytest.param(
            Scenario(Kind.STRIKE, LONE_SPEARMAN, Side("great-eagle", 1, "Wicked Claws")),
            Fraction(0),
            Fraction(0),
            id="monstrous-creature",
        ),
        pytest.param(
            Scenario(Kind.STRIKE, LONE_SPEARMAN, replace(PHOENIX_GUARD, models=1)),
            one_attack(replace(WARDED_BLOW, killing_blow=True)).unsaved,
            one_attack(WARDED_BLOW).unsaved,
            id="ward-still-rolled",
            marks=pytest.mark.xfail(
                strict=True,
                reason="Killing Blow needs casualty classes at Remove Casualties, and the "
                "expectation assumes no blows back while the Phoenix Guard strike first",
            ),
        ),
        pytest.param(
            Scenario(
                Kind.SHOOT, Side("elven-archers", 1, frontage=1), Side("maneaters", 1), distance=10
            ),
            Fraction(0),
            Fraction(0),
            id="shooting",
        ),
    ],
)
def test_killing_blow(scenario: Scenario, printed: Fraction, plain: Fraction) -> None:
    """A natural 6 To Wound in combat denies the armour save and slays the model outright.

    One blow can fell a three-Wound Maneater, but not a Monstrous Creature, which the
    rule does not name, and no shot can. Against a one-Wound Phoenix Guard the blow
    still meets the 6+ ward.
    """
    with_rule = scenario.adding("killing-blow", Role.ATTACKER)
    assert (
        resolve(with_rule).casualties.get(1, 0),
        resolve(scenario).casualties.get(1, 0),
    ) == (printed, plain)


MANEATER = Side("maneaters", 1, "Hand Weapon")
EAGLE_MAW = Scenario(
    Kind.STRIKE, Side("great-eagle", 1, "Serrated Maw"), replace(MANEATER, models=2)
)
LONE_SWORD = Scenario(Kind.STRIKE, Side("elven-spearmen", 1, "Hand Weapon", frontage=1), MANEATER)
LONE_BOW = Scenario(
    Kind.SHOOT, Side("elven-archers", 1, "Longbow", frontage=1), MANEATER, distance=10
)
D3 = {wounds: Fraction(1, 3) for wounds in (1, 2, 3)}


@pytest.mark.parametrize(
    ("printed", "plain", "blows", "models", "damage"),
    [
        pytest.param(
            EAGLE_MAW,
            EAGLE_MAW.without("multiple-wounds", Role.ATTACKER),
            [Attack(COMBAT, 5, 4, 4, foe_weapon_skill=4, armour_value=6, armour_bane=2)] * 3,
            2,
            {2: Fraction(1)},
            id="maw-of-two-no-spill-over",
        ),
        pytest.param(
            LONE_SWORD.adding("multiple-wounds", Role.ATTACKER, Carrier.WEAPON, x=3),
            LONE_SWORD,
            [Attack(COMBAT, 4, 3, 4, foe_weapon_skill=4, armour_value=6)],
            1,
            {3: Fraction(1)},
            id="sword-of-three",
        ),
        pytest.param(
            LONE_BOW.adding("multiple-wounds", Role.ATTACKER, Carrier.WEAPON, x="D3"),
            LONE_BOW,
            [Attack(SHOOTING, 4, 3, 4, armour_value=6, armour_bane=1)],
            1,
            D3,
            id="bow-of-d3",
        ),
    ],
)
def test_multiple_wounds(
    printed: Scenario,
    plain: Scenario,
    blows: list[Attack],
    models: int,
    damage: dict[int, Fraction],
) -> None:
    """Each unsaved wound takes X Wounds from a three-Wound Maneater, the excess lost.

    Two of the Great Eagle's maw blows fell one Maneater and a third cannot fell the
    next; a sword of three fells one; a D3 is rolled for each unsaved wound.
    """
    odds = [one_attack(blow) for blow in blows]
    assert (resolve(printed).casualties, resolve(plain).casualties) == (
        casualties(odds, models=models, wounds=3, damage=damage),
        casualties(odds, models=models, wounds=3),
    )


IRONBREAKERS_PARRY = Attack(
    COMBAT, 4, 3, 4, foe_weapon_skill=5, armour_value=3, ward=6, save_re_rolls=ONES
)


ARROWS_INTO_SPEARMEN = Attack(SHOOTING, 4, 3, 3, armour_value=5, armour_bane=1)


@pytest.mark.parametrize(
    ("scenario", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.STRIKE, SPEARS, replace(SPEARMEN, weapon="Hand Weapon")),
            replace(SPEAR_INTO_SPEARMEN, armour_value=4),
            SPEAR_INTO_SPEARMEN,
            id="hand-weapon",
        ),
        pytest.param(
            Scenario(Kind.STRIKE, SPEARS, SPEARMEN),
            SPEAR_INTO_SPEARMEN,
            SPEAR_INTO_SPEARMEN,
            id="spear",
        ),
        pytest.param(
            Scenario(Kind.STRIKE, SPEARS, IRONBREAKERS),
            IRONBREAKERS_PARRY,
            IRONBREAKERS_PARRY,
            id="capped-at-3+",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, ARCHERS, replace(SPEARMEN, weapon="Hand Weapon"), distance=10),
            ARROWS_INTO_SPEARMEN,
            ARROWS_INTO_SPEARMEN,
            id="shot",
        ),
    ],
)
def test_parry(scenario: Scenario, printed: Attack, plain: Attack) -> None:
    """A hand weapon and shield in combat better the save by 1, to no better than 3+."""
    assert _with_and_without(scenario, scenario.without("parry", Role.DEFENDER)) == (
        _unsaved(printed),
        _unsaved(plain),
    )


TWO_HANDED = Side("elven-spearmen", 10, "Great Weapon", equipment=("Great Weapon",))


@pytest.mark.parametrize(
    ("scenario", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.STRIKE, SPEARS, TWO_HANDED),
            replace(SPEAR_INTO_SPEARMEN, armour_value=6),
            SPEAR_INTO_SPEARMEN,
            id="struck-wielding-it",
            marks=pytest.mark.xfail(
                strict=True, reason="Requires Two Hands needs its bar to forbid the shield"
            ),
        ),
        pytest.param(
            Scenario(Kind.STRIKE, SPEARS, replace(TWO_HANDED, weapon="Hand Weapon")),
            replace(SPEAR_INTO_SPEARMEN, armour_value=4),
            replace(SPEAR_INTO_SPEARMEN, armour_value=4),
            id="struck-wielding-a-hand-weapon",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, ARCHERS, TWO_HANDED, distance=10),
            ARROWS_INTO_SPEARMEN,
            ARROWS_INTO_SPEARMEN,
            id="shot",
        ),
    ],
)
def test_requires_two_hands(scenario: Scenario, printed: Attack, plain: Attack) -> None:
    """Spearmen swinging a great weapon cannot use their shield in combat: 6+ rather than 5+.

    Fighting with a hand weapon instead, the shield stands and parries; against
    shooting it counts whatever is in hand.
    """
    assert _with_and_without(scenario, scenario.without("requires-two-hands", Role.DEFENDER)) == (
        _unsaved(printed),
        _unsaved(plain),
    )


HOETH_INTO_IRONBREAKERS = Attack(
    COMBAT, 6, 5, 4, foe_weapon_skill=5, armour_value=3, armour_piercing=-2, save_re_rolls=ONES
)


@pytest.mark.parametrize(
    ("attackers", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.STRIKE, SPEARS, IRONBREAKERS),
            replace(IRONBREAKERS_PARRY, ward=6),
            replace(IRONBREAKERS_PARRY, ward=None),
            id="mundane-spears",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, ARCHERS, IRONBREAKERS, distance=10),
            GROMRIL_SHOT_RE_ROLLED,
            replace(GROMRIL_SHOT_RE_ROLLED, ward=None),
            id="mundane-arrows",
        ),
        pytest.param(
            Scenario(Kind.STRIKE, SWORDS_OF_HOETH, IRONBREAKERS),
            HOETH_INTO_IRONBREAKERS,
            HOETH_INTO_IRONBREAKERS,
            id="magical-swords",
        ),
    ],
)
def test_runes_of_protection(attackers: Scenario, printed: Attack, plain: Attack) -> None:
    """Ironbreakers take a 6+ ward against a non-magical attack, struck or shot."""
    assert _with_and_without(
        attackers, attackers.without("runes-of-protection", Role.DEFENDER)
    ) == (_unsaved(printed), _unsaved(plain))


@pytest.mark.parametrize(
    ("scenario", "printed", "plain"),
    [
        pytest.param(
            Scenario(Kind.STRIKE, SWORDS, PHOENIX_GUARD),
            Attack(COMBAT, 4, 3, 3, foe_weapon_skill=5, armour_value=4, ward=6),
            Attack(COMBAT, 4, 3, 3, foe_weapon_skill=5, armour_value=4),
            id="mundane-swords",
        ),
        pytest.param(
            Scenario(Kind.STRIKE, SWORDS_OF_HOETH, PHOENIX_GUARD),
            Attack(COMBAT, 6, 5, 3, foe_weapon_skill=5, armour_value=4, armour_piercing=-2),
            Attack(COMBAT, 6, 5, 3, foe_weapon_skill=5, armour_value=4, armour_piercing=-2),
            id="magical-swords",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, ARCHERS, PHOENIX_GUARD, distance=10),
            ARROWS_INTO_PHOENIX_GUARD,
            replace(ARROWS_INTO_PHOENIX_GUARD, ward=None),
            id="mundane-arrows",
        ),
        pytest.param(
            Scenario(Kind.SHOOT, _sisters("Bow of Avelorn"), PHOENIX_GUARD, distance=10),
            Attack(SHOOTING, 5, 3, 3, armour_value=4, armour_piercing=-1, armour_bane=2),
            Attack(SHOOTING, 5, 3, 3, armour_value=4, armour_piercing=-1, armour_bane=2),
            id="magical-bow",
        ),
    ],
)
def test_witness_to_destiny(scenario: Scenario, printed: Attack, plain: Attack) -> None:
    """Phoenix Guard take a 6+ ward against a non-magical attack, struck or shot."""
    assert _with_and_without(scenario, scenario.without("witness-to-destiny", Role.DEFENDER)) == (
        _unsaved(printed),
        _unsaved(plain),
    )
