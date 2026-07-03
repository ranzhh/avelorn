"""Make Panic Tests: hand-computed goldens over synthetic casualty masses."""

from fractions import Fraction
from pathlib import Path

import pytest

from avelorn.core.loading import load_yaml
from avelorn.tow.combat.panic import make_panic_tests
from avelorn.tow.combat.shooting import ShootingResult
from avelorn.tow.schema.psychology import PanicCause
from avelorn.tow.schema.rule import RerollEffect, Rule
from avelorn.tow.schema.stage import Stage
from avelorn.tow.schema.unit import Unit

DATA_DIR = Path(__file__).parents[3] / "data"

# Elven Spearmen carry Ld 8: a Leadership test passes 26/36.
P_PASS = float(Fraction(26, 36))


def _spearmen() -> Unit:
    return load_yaml(DATA_DIR / "tow/armies/high-elf-realms/units/elven-spearmen.yaml", Unit)


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
    panic = make_panic_tests(_result([0.0, 0.0, 1.0], size=8), _spearmen())
    assert panic.p_test == 0.0
    assert panic.p_holds == 1.0


def test_more_than_a_quarter_tests_against_leadership() -> None:
    """3 of 8 lost forces the test; holding means passing it (Ld 8)."""
    panic = make_panic_tests(_result([0.0, 0.0, 0.0, 1.0], size=8), _spearmen())
    assert panic.p_test == 1.0
    assert panic.p_holds == pytest.approx(P_PASS)
    assert panic.p_falls_back == pytest.approx(1 - P_PASS)  # 5 of 8 remain: > half
    assert panic.p_flees == 0.0


def test_fall_back_or_flee_splits_on_half_the_battle_strength() -> None:
    """Failing at 6 of 10 remaining falls back; at 5 of 10 it flees.

    "More than half (50%) ... still remain" is strict: exactly half
    flees.
    """
    six_remain = make_panic_tests(_result([0.0] * 4 + [1.0], size=10), _spearmen())
    assert six_remain.p_falls_back == pytest.approx(1 - P_PASS)
    assert six_remain.p_flees == 0.0

    five_remain = make_panic_tests(_result([0.0] * 5 + [1.0], size=10), _spearmen())
    assert five_remain.p_falls_back == 0.0
    assert five_remain.p_flees == pytest.approx(1 - P_PASS)


def test_battle_strength_governs_the_split() -> None:
    """A unit already whittled before the phase flees more readily.

    10 remain of a 24-model battle line; losing 3 leaves 7 <= 12: flee.
    """
    result = _result([0.0, 0.0, 0.0, 1.0], size=10)
    panic = make_panic_tests(result, _spearmen(), battle_strength=24)
    assert panic.p_flees == pytest.approx(1 - P_PASS)
    assert panic.p_falls_back == 0.0


def test_a_wiped_unit_is_destroyed_not_tested() -> None:
    """Losing every model leaves nothing to test."""
    panic = make_panic_tests(_result([0.0, 0.0, 1.0], size=2), _spearmen())
    assert panic.p_destroyed == 1.0
    assert panic.p_test == 0.0


def test_outcomes_partition_the_distribution() -> None:
    """Across a spread of casualty masses the outcomes sum to 1."""
    spread = [0.2, 0.1, 0.3, 0.25, 0.15]  # 0..4 of 4
    panic = make_panic_tests(_result(spread, size=4), _spearmen())
    total = panic.p_holds + panic.p_falls_back + panic.p_flees + panic.p_destroyed
    assert total == pytest.approx(1.0)


def test_missing_or_zero_size_rejected() -> None:
    """The panic step needs a real unit size."""
    with pytest.raises(ValueError, match="unit's size"):
        make_panic_tests(_result([1.0], size=0), _spearmen())


def test_battle_strength_below_current_size_rejected() -> None:
    """A unit cannot outnumber its own start-of-battle strength."""
    with pytest.raises(ValueError, match="battle strength"):
        make_panic_tests(_result([1.0, 0.0], size=10), _spearmen(), battle_strength=5)


def _valour(causes: list[PanicCause]) -> dict[str, Rule]:
    return {
        "Valour of Ages": Rule(
            id="valour-of-ages",
            name="Valour of Ages",
            paragraphs=["Re-roll text."],
            effects=[RerollEffect(kind="re-roll", stage=Stage.MAKE_PANIC_TESTS, causes=causes)],
        )
    }


def test_reroll_effect_lifts_the_pass_probability() -> None:
    """A failed test is taken once more: p' = p + (1 - p) * p.

    Spearmen list Valour of Ages; with its effect in the registry the
    heavy-casualties test re-rolls (Ld 8: 26/36 -> 0.9228...).
    """
    result = _result([0.0, 0.0, 0.0, 1.0], size=8)
    rules = _valour([PanicCause.HEAVY_CASUALTIES, PanicCause.FLED_THROUGH])
    panic = make_panic_tests(result, _spearmen(), rules=rules)
    lifted = P_PASS + (1 - P_PASS) * P_PASS
    assert panic.reroll_from == "Valour of Ages"
    assert panic.p_holds == pytest.approx(lifted)
    assert panic.p_falls_back == pytest.approx(1 - lifted)


def test_reroll_restricted_to_other_causes_does_not_apply() -> None:
    """A fled-through-only re-roll grants nothing on a heavy-casualties test."""
    result = _result([0.0, 0.0, 0.0, 1.0], size=8)
    rules = _valour([PanicCause.FLED_THROUGH])
    panic = make_panic_tests(result, _spearmen(), rules=rules)
    assert panic.reroll_from is None
    assert panic.p_holds == pytest.approx(P_PASS)


def test_no_registry_means_no_reroll() -> None:
    """Without the rules registry the listed rule stays inert."""
    result = _result([0.0, 0.0, 0.0, 1.0], size=8)
    panic = make_panic_tests(result, _spearmen())
    assert panic.reroll_from is None
    assert panic.p_holds == pytest.approx(P_PASS)
