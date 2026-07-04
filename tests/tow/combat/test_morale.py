"""Morale tests: hand-computed goldens over synthetic distributions."""

from fractions import Fraction

import pytest

from avelorn.core.registry import Registry
from avelorn.tow.combat.melee import CombatResult
from avelorn.tow.combat.morale import SideBreak, break_test, make_panic_tests
from avelorn.tow.combat.shooting import ShootingResult
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.psychology import PanicCause
from avelorn.tow.schema.rule import RerollEffect, Rule
from avelorn.tow.schema.stage import Stage

REPO = TOWRepository()

# Elven Spearmen carry Ld 8: a Leadership test passes 26/36.
P_PASS = float(Fraction(26, 36))


def _result(casualties: list[float], size: int) -> ShootingResult:
    # Only the casualty distribution and unit size matter to the panic
    # step; the attack-chain fields are inert scaffolding here.
    return ShootingResult(
        shots=len(casualties) - 1,
        hit_target=3,
        wound_target=4,
        save_target=None,
        ward_target=None,
        p_hit=0.0,
        p_wound=0.0,
        p_unsaved=0.0,
        distribution=list(casualties),
        casualties=list(casualties),
        target_models=size,
    )


def test_a_quarter_exactly_does_not_test() -> None:
    """The trigger is strictly more than 25%: 2 of 8 lost is no test."""
    panic = make_panic_tests(_result([0.0, 0.0, 1.0], size=8), REPO.units["elven-spearmen"])
    assert panic.p_test == 0.0
    assert panic.p_holds == 1.0


def test_more_than_a_quarter_tests_against_leadership() -> None:
    """3 of 8 lost forces the test; holding means passing it (Ld 8)."""
    panic = make_panic_tests(_result([0.0, 0.0, 0.0, 1.0], size=8), REPO.units["elven-spearmen"])
    assert panic.p_test == 1.0
    assert panic.p_holds == pytest.approx(P_PASS)
    assert panic.p_falls_back == pytest.approx(1 - P_PASS)  # 5 of 8 remain: > half
    assert panic.p_flees == 0.0


def test_fall_back_or_flee_splits_on_half_the_battle_strength() -> None:
    """Failing at 6 of 10 remaining falls back; at 5 of 10 it flees.

    "More than half (50%) ... still remain" is strict: exactly half
    flees.
    """
    six_remain = make_panic_tests(
        _result([0.0] * 4 + [1.0], size=10), REPO.units["elven-spearmen"]
    )
    assert six_remain.p_falls_back == pytest.approx(1 - P_PASS)
    assert six_remain.p_flees == 0.0

    five_remain = make_panic_tests(
        _result([0.0] * 5 + [1.0], size=10), REPO.units["elven-spearmen"]
    )
    assert five_remain.p_falls_back == 0.0
    assert five_remain.p_flees == pytest.approx(1 - P_PASS)


def test_battle_strength_governs_the_split() -> None:
    """A unit already whittled before the phase flees more readily.

    10 remain of a 24-model battle line; losing 3 leaves 7 <= 12: flee.
    """
    result = _result([0.0, 0.0, 0.0, 1.0], size=10)
    panic = make_panic_tests(result, REPO.units["elven-spearmen"], battle_strength=24)
    assert panic.p_flees == pytest.approx(1 - P_PASS)
    assert panic.p_falls_back == 0.0


def test_a_wiped_unit_is_destroyed_not_tested() -> None:
    """Losing every model leaves nothing to test."""
    panic = make_panic_tests(_result([0.0, 0.0, 1.0], size=2), REPO.units["elven-spearmen"])
    assert panic.p_destroyed == 1.0
    assert panic.p_test == 0.0


def test_outcomes_partition_the_distribution() -> None:
    """Across a spread of casualty masses the outcomes sum to 1."""
    spread = [0.2, 0.1, 0.3, 0.25, 0.15]  # 0..4 of 4
    panic = make_panic_tests(_result(spread, size=4), REPO.units["elven-spearmen"])
    total = panic.p_holds + panic.p_falls_back + panic.p_flees + panic.p_destroyed
    assert total == pytest.approx(1.0)


def test_missing_or_zero_size_rejected() -> None:
    """The panic step needs a real unit size."""
    with pytest.raises(ValueError, match="unit's size"):
        make_panic_tests(_result([1.0], size=0), REPO.units["elven-spearmen"])


def test_battle_strength_below_current_size_rejected() -> None:
    """A unit cannot outnumber its own start-of-battle strength."""
    with pytest.raises(ValueError, match="battle strength"):
        make_panic_tests(
            _result([1.0, 0.0], size=10), REPO.units["elven-spearmen"], battle_strength=5
        )


def _valour(causes: list[PanicCause]) -> Registry[Rule]:
    rule = Rule(
        id="valour-of-ages",
        name="Valour of Ages",
        paragraphs=["Re-roll text."],
        effects=[RerollEffect(kind="re-roll", stage=Stage.MAKE_PANIC_TESTS, causes=causes)],
    )
    return Registry([rule], kind="rule")


def test_reroll_effect_lifts_the_pass_probability() -> None:
    """A failed test is taken once more: p' = p + (1 - p) * p.

    Spearmen list Valour of Ages; with its effect in the registry the
    heavy-casualties test re-rolls (Ld 8: 26/36 -> 0.9228...).
    """
    result = _result([0.0, 0.0, 0.0, 1.0], size=8)
    rules = _valour([PanicCause.HEAVY_CASUALTIES, PanicCause.FLED_THROUGH])
    panic = make_panic_tests(result, REPO.units["elven-spearmen"], rules=rules)
    lifted = P_PASS + (1 - P_PASS) * P_PASS
    assert panic.reroll_from == "Valour of Ages"
    assert panic.p_holds == pytest.approx(lifted)
    assert panic.p_falls_back == pytest.approx(1 - lifted)


def test_reroll_restricted_to_other_causes_does_not_apply() -> None:
    """A fled-through-only re-roll grants nothing on a heavy-casualties test."""
    result = _result([0.0, 0.0, 0.0, 1.0], size=8)
    rules = _valour([PanicCause.FLED_THROUGH])
    panic = make_panic_tests(result, REPO.units["elven-spearmen"], rules=rules)
    assert panic.reroll_from is None
    assert panic.p_holds == pytest.approx(P_PASS)


def test_no_registry_means_no_reroll() -> None:
    """Without the rules registry the listed rule stays inert."""
    result = _result([0.0, 0.0, 0.0, 1.0], size=8)
    panic = make_panic_tests(result, REPO.units["elven-spearmen"])
    assert panic.reroll_from is None
    assert panic.p_holds == pytest.approx(P_PASS)


def test_valour_of_ages_applies_from_the_data_file() -> None:
    """End to end: the authored effect re-rolls the spearmen's panic test."""
    registry = REPO.rules
    result = _result([0.0, 0.0, 0.0, 1.0], size=8)
    panic = make_panic_tests(result, REPO.units["elven-spearmen"], rules=registry)
    assert panic.reroll_from == "Valour of Ages"
    assert panic.p_holds == pytest.approx(P_PASS + (1 - P_PASS) * P_PASS)


# --- Break test: 2D6 + margin vs Leadership, three outcomes ---


def _combat(margin: dict[int, float]) -> CombatResult:
    # Only the signed margin distribution matters to the break test; the
    # win/draw/loss summaries are inert scaffolding here.
    return CombatResult(p_a_wins=0.0, p_draw=0.0, p_b_wins=0.0, margin=margin)


def test_break_test_three_outcomes_at_a_fixed_margin() -> None:
    """B loses by 3 against Ld 8: 2D6 splits Break / Fall Back / Give Ground.

    Break (natural > 8): 9,10,11,12 = 10/36. Fall Back (natural <= 8,
    natural+3 > 8, i.e. 6,7,8) = 16/36. Give Ground (the rest, incl. the
    double 1) = 10/36. A is the winner, so it takes no test at all.
    """
    result = break_test(
        _combat({3: 1.0}), REPO.units["elven-spearmen"], REPO.units["elven-spearmen"]
    )
    assert result.b.p_breaks == pytest.approx(10 / 36)
    assert result.b.p_falls_back == pytest.approx(16 / 36)
    assert result.b.p_gives_ground == pytest.approx(10 / 36)
    assert result.a == SideBreak(0.0, 0.0, 0.0)  # winner never tests
    assert result.p_draw == pytest.approx(0.0)


def test_break_test_double_one_always_gives_ground() -> None:
    """Even under a crushing margin, a natural double 1 Gives Ground.

    Margin 100 vs Ld 8: every non-double-1 roll within Leadership would Fall
    Back, so Give Ground is exactly the 1/36 double 1 — proof the override
    fires.
    """
    result = break_test(
        _combat({100: 1.0}), REPO.units["elven-spearmen"], REPO.units["elven-spearmen"]
    )
    assert result.b.p_gives_ground == pytest.approx(1 / 36)
    assert result.b.p_breaks == pytest.approx(10 / 36)
    assert result.b.p_falls_back == pytest.approx(25 / 36)


def test_break_test_draw_takes_no_test() -> None:
    """A drawn combat: neither side tests."""
    result = break_test(
        _combat({0: 1.0}), REPO.units["elven-spearmen"], REPO.units["elven-spearmen"]
    )
    assert result.p_draw == pytest.approx(1.0)
    assert result.a == SideBreak(0.0, 0.0, 0.0)
    assert result.b == SideBreak(0.0, 0.0, 0.0)


def test_break_test_scores_whichever_side_lost() -> None:
    """Either side can be the loser; the split is symmetric here.

    A wins by 2 half the time, B wins by 2 the other half (Ld 8 both), so
    each side's loser-outcomes are identical and each side loses half the
    time. The six outcome masses and the (zero) draw sum to 1.
    """
    result = break_test(
        _combat({2: 0.5, -2: 0.5}), REPO.units["elven-spearmen"], REPO.units["elven-spearmen"]
    )
    assert result.a == result.b
    a_lost = result.a.p_gives_ground + result.a.p_falls_back + result.a.p_breaks
    b_lost = result.b.p_gives_ground + result.b.p_falls_back + result.b.p_breaks
    assert a_lost == pytest.approx(0.5)  # A is the loser half the time
    assert a_lost + b_lost + result.p_draw == pytest.approx(1.0)
