"""Kernel tests against verbatim rulebook values (tow.whfb.app)."""

import re
from collections.abc import Callable
from fractions import Fraction

import pytest
from oracle.procedure import Attack, Phase, one_attack

from avelorn.core.distribution import Distribution
from avelorn.tow.kernels import (
    Confirm,
    Die,
    Standing,
    armour_save_target,
    d6,
    falls_back_in_good_order,
    heavy_casualties,
    hit_probability,
    leadership_test,
    melee_hit_probability,
    melee_hit_target,
    remove_casualties,
    save_probability,
    shooting_hit,
    shooting_hit_target,
    success,
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
    ("target", "expected"),
    [
        (2, 5 / 6),
        (3, 4 / 6),
        (4, 3 / 6),
        (6, 1 / 6),
        (7, 1 / 6),  # no confirm: only a natural 6, still 1/6
        (9, 1 / 6),
        (1, 5 / 6),  # natural 1 always fails
    ],
)
def test_melee_hit_probability(target: int, expected: float) -> None:
    """Natural 6 always hits, natural 1 always fails, no 7+ confirmation."""
    assert melee_hit_probability(target) == pytest.approx(expected)


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


@pytest.mark.parametrize("modifier", [0, -1, -2])
@pytest.mark.parametrize("ballistic_skill", range(6, 11))
def test_ballistic_skill_six_or_higher_hits_as_the_oracle(
    ballistic_skill: int, modifier: int
) -> None:
    """A first roll on 2+ shifted by the modifier, then the chart's re-roll unmodified."""
    attack = Attack(
        Phase.SHOOTING, skill=ballistic_skill, strength=10, toughness=1, hit_modifier=modifier
    )
    always_wounds = Fraction(5, 6)

    hit = success(shooting_hit(ballistic_skill, modifier))

    assert hit * always_wounds == one_attack(attack).unsaved


@pytest.mark.parametrize(
    ("ballistic_skill", "modifier", "message"),
    [(6, -5, "BS 6 at -5 needs 7+ on its first roll"), (11, 0, "BS 11 is off the printed chart")],
)
def test_shooting_hit_refuses_a_roll_the_chart_does_not_print(
    ballistic_skill: int, modifier: int, message: str
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        shooting_hit(ballistic_skill, modifier)


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


_SIXTH = Fraction(1, 6)


def _misses(*faces: int) -> dict[Die, Fraction]:
    return {Die(face, False): _SIXTH for face in faces}


@pytest.mark.parametrize(
    ("target", "rerolls", "confirm", "expected"),
    [
        (
            7,
            frozenset(),
            Confirm.SECOND_DIE,
            {**_misses(1, 2, 3, 4, 5), Die(6, True): _SIXTH / 2, Die(6, False): _SIXTH / 2},
        ),
        (9, frozenset(), Confirm.ALWAYS, {**_misses(1, 2, 3, 4, 5), Die(6, True): _SIXTH}),
        (7, frozenset(), Confirm.NEVER, _misses(1, 2, 3, 4, 5, 6)),
        (
            1,
            frozenset(),
            Confirm.NEVER,
            {**_misses(1), **{Die(f, True): _SIXTH for f in range(2, 7)}},
        ),
        (
            2,
            frozenset({Die(1, False)}),
            Confirm.NEVER,
            {Die(1, False): _SIXTH**2, **{Die(f, True): _SIXTH + _SIXTH**2 for f in range(2, 7)}},
        ),
        (
            7,
            frozenset({Die(6, False)}),
            Confirm.SECOND_DIE,
            {
                **{Die(f, False): Fraction(13, 72) for f in range(1, 6)},
                Die(6, True): Fraction(13, 144),
                Die(6, False): Fraction(1, 144),
            },
        ),
    ],
    ids=[
        "shooting-7-plus-confirms-on-a-second-4-plus",
        "combat-9-plus-hits-on-a-natural-6",
        "wound-pushed-to-7-always-fails",
        "target-1-still-fails-a-natural-1",
        "re-rolled-natural-1-stands",
        "failed-confirmation-re-rolls-the-whole-die",
    ],
)
def test_d6_lands_every_face_as_printed(
    target: int, rerolls: frozenset[Die], confirm: Confirm, expected: dict[Die, Fraction]
) -> None:
    """The one die walk keeps each natural face, so face-triggered rules can read it."""
    assert d6(target, rerolls, confirm) == Distribution(expected)


@pytest.mark.parametrize(
    ("leadership", "expected"),
    [
        (7, Fraction(21, 36)),
        (8, Fraction(26, 36)),
        (9, Fraction(30, 36)),
        (10, Fraction(33, 36)),
    ],
)
def test_leadership_matches_hand_count(leadership: int, expected: Fraction) -> None:
    """Golden 2D6 cumulative counts for the common Leadership values."""
    assert leadership_test(leadership) == expected


def test_leadership_natural_bounds() -> None:
    """The double 1 always passes; the double 6 always fails."""
    assert leadership_test(1) == Fraction(1, 36)
    assert leadership_test(12) == Fraction(35, 36)
    assert leadership_test(20) == Fraction(35, 36)


def test_zero_or_dash_fails_automatically() -> None:
    """A Leadership of 0 or "-" automatically fails the test."""
    assert leadership_test(0) == Fraction(0)
    assert leadership_test(None) == Fraction(0)


@pytest.mark.parametrize(
    ("standing", "wounds", "after"),
    [
        pytest.param(Standing(2, 1), 1, Standing(1, 0), id="the-damaged-model-falls-first"),
        pytest.param(Standing(2, 1), 4, Standing(0, 0), id="the-last-model-keeps-no-damage"),
        pytest.param(Standing(3, 1), 2, Standing(2, 1), id="a-wound-carries-to-the-next-model"),
    ],
)
def test_remove_casualties_carries_wounds_across_models(
    standing: Standing, wounds: int, after: Standing
) -> None:
    """Wounds carry across Two-Wound models."""
    assert remove_casualties(standing, wounds, 2) == after


@pytest.mark.parametrize(
    ("kernel", "message"),
    [
        pytest.param(
            lambda: remove_casualties(Standing(10, 5), 0, 1),
            "a damaged model cannot have lost 5 of 1 Wounds",
            id="damage-beyond-the-model",
        ),
        pytest.param(
            lambda: heavy_casualties(11, 10),
            "11 models exceed the 10 at the start of the phase",
            id="more-models-than-at-the-start",
        ),
        pytest.param(
            lambda: falls_back_in_good_order(11, 10),
            "11 models exceed the battle strength of 10",
            id="more-models-than-the-battle-strength",
        ),
    ],
)
def test_an_impossible_standing_is_refused(kernel: Callable[[], object], message: str) -> None:
    """A standing no table can hold is refused."""
    with pytest.raises(ValueError, match=message):
        kernel()
