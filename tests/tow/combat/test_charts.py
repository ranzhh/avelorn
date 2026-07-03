"""Chart tests against verbatim rulebook values (tow.whfb.app)."""

import pytest

from avelorn.tow.combat.charts import (
    armour_save_target,
    hit_probability,
    melee_hit_target,
    save_probability,
    shooting_hit_target,
    wound_probability,
    wound_target,
)


@pytest.mark.parametrize(
    ("weapon_skill", "target_weapon_skill", "expected"),
    [
        (4, 4, 4),  # equal WS: 4+
        (5, 4, 3),  # higher, not double: 3+
        (7, 3, 2),  # more than double (7 > 6): 2+
        (6, 3, 3),  # exactly double is not "more than": 3+
        (3, 7, 5),  # target more than double (7 > 6): 5+
        (3, 6, 4),  # target exactly double is not "more than": 4+
        (1, 1, 4),  # chart corner
        (10, 1, 2),  # far corner
        (1, 10, 5),  # far corner
    ],
)
def test_melee_hit_target(weapon_skill: int, target_weapon_skill: int, expected: int) -> None:
    """Spot checks against the verbatim WS-vs-WS close-combat To Hit chart."""
    assert melee_hit_target(weapon_skill, target_weapon_skill) == expected


@pytest.mark.parametrize(
    ("ballistic_skill", "modifier", "expected"),
    [(1, 0, 6), (3, 0, 4), (4, 0, 3), (5, 0, 2), (4, -1, 4), (2, -2, 7), (5, 1, 1)],
)
def test_shooting_hit_target(ballistic_skill: int, modifier: int, expected: int) -> None:
    """To Hit is 7 minus BS, shifted by (negative) modifiers."""
    assert shooting_hit_target(ballistic_skill, modifier) == expected


@pytest.mark.parametrize(
    ("strength", "toughness", "expected"),
    [
        (1, 1, 4),
        (3, 3, 4),
        (3, 4, 5),
        (3, 5, 6),
        (3, 8, 6),  # 6+ band extends while T - S <= 5
        (1, 7, None),  # printed "-": cannot wound
        (3, 9, None),
        (4, 2, 2),  # 2+ floor
        (10, 10, 4),
        (5, 10, 6),
    ],
)
def test_wound_target_matches_printed_chart(
    strength: int, toughness: int, expected: int | None
) -> None:
    """Spot checks against the verbatim S vs T chart, including dashes."""
    assert wound_target(strength, toughness) == expected


@pytest.mark.parametrize(
    ("armour_value", "armour_piercing", "expected"),
    [
        (5, 0, 5),
        (5, -1, 6),  # rulebook example: AP -1 turns 5+ into 6
        (6, -1, None),  # pushed past 6: no save
        (None, -3, None),
        (7, 0, None),  # unarmoured
        (2, -4, 6),
    ],
)
def test_armour_save_target(
    armour_value: int | None, armour_piercing: int, expected: int | None
) -> None:
    """AP worsens the save; past 6+ there is no save."""
    assert armour_save_target(armour_value, armour_piercing) == expected


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        (3, 4 / 6),
        (6, 1 / 6),
        (1, 5 / 6),  # natural 1 always fails
        (7, 1 / 12),  # natural 6 confirmed on 4+
        (8, 1 / 18),
        (9, 1 / 36),
        (10, 0.0),
    ],
)
def test_hit_probability(target: int, expected: float) -> None:
    """Hit probabilities, including the 7+ confirm rule."""
    assert hit_probability(target) == pytest.approx(expected)


def test_save_probability_none_means_no_save() -> None:
    """No save target means the wound always goes through."""
    assert save_probability(None) == 0.0
    assert save_probability(5) == pytest.approx(2 / 6)


def test_wound_probability() -> None:
    """Wound probabilities follow the target; None (cannot wound) is 0."""
    assert wound_probability(None) == 0.0
    assert wound_probability(4) == pytest.approx(3 / 6)
    assert wound_probability(2) == pytest.approx(5 / 6)
    assert wound_probability(6) == pytest.approx(1 / 6)
