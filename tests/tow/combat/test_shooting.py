"""Shooting chain tests, golden values hand-computed from the rulebook charts."""

from dataclasses import replace
from pathlib import Path

import pytest

from avelorn.core.loading import load_yaml, load_yaml_dir
from avelorn.tow.combat.attack import AttackProfile, Outcome, RollState, Stage, Transform
from avelorn.tow.combat.shooting import _remove_casualties, shoot, shoot_unit
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon

DATA_DIR = Path(__file__).parents[3] / "data"

ARMOURY = {a.name: a for a in load_yaml_dir(DATA_DIR / "tow/armour", Armour)}


def load_unit(army: str, slug: str) -> Unit:
    """Load and validate a unit from the data/ tree.

    Returns:
        The parsed unit model.
    """
    return load_yaml(DATA_DIR / f"tow/armies/{army}/units/{slug}.yaml", Unit)


def load_weapon(slug: str) -> Weapon:
    """Load and validate a weapon from the data/ tree.

    Returns:
        The parsed weapon model.
    """
    return load_yaml(DATA_DIR / f"tow/weapons/{slug}.yaml", Weapon)


def test_shoot_golden_chain() -> None:
    """BS4, S3 vs T3, 5+ save: p = 2/3 * 1/2 * 2/3 = 2/9 per shot."""
    result = shoot(3, ballistic_skill=4, strength=3, toughness=3, armour_value=5)
    assert result.hit_target == 3
    assert result.wound_target == 4
    assert result.save_target == 5
    assert result.p_unsaved == pytest.approx(2 / 9)
    assert result.expected_wounds == pytest.approx(2 / 3)
    assert sum(result.distribution) == pytest.approx(1.0)
    assert result.distribution[0] == pytest.approx((7 / 9) ** 3)


def test_shoot_ward_save_stacks_multiplicatively() -> None:
    """A 4+ ward halves the unsaved-wound probability."""
    base = shoot(1, ballistic_skill=4, strength=3, toughness=3)
    warded = shoot(1, ballistic_skill=4, strength=3, toughness=3, ward_target=4)
    assert warded.p_unsaved == pytest.approx(base.p_unsaved / 2)


def test_shoot_impossible_wound_kills_nothing() -> None:
    """S1 vs T7 is a printed dash: zero wounds regardless of dice."""
    result = shoot(10, ballistic_skill=5, strength=1, toughness=7)
    assert result.p_unsaved == 0.0
    assert result.distribution[0] == pytest.approx(1.0)


def test_shoot_unit_archers_vs_spearmen() -> None:
    """End-to-end from data files: 3 Elven Archers shoot Elven Spearmen.

    Spearmen carry light armour (6+) and a shield (+1), so they save on
    5+; the longbow has no AP. Expected kills = 3 * 2/9.
    """
    archers = load_unit("high-elf-realms", "elven-archers")
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    result = shoot_unit(
        archers, spearmen, shooters=3, weapon=load_weapon("longbow"), armoury=ARMOURY
    )
    assert result.hit_target == 3  # BS 4
    assert result.save_target == 5  # 7 - light armour - shield
    assert result.expected_wounds == pytest.approx(2 / 3)
    assert any("Hand Weapon" in note for note in result.notes)  # melee gear unfactored
    assert any("Valour of Ages" in note for note in result.notes)
    assert any("Armour Bane (1)" in note for note in result.notes)  # weapon rule unfactored


def test_shoot_unit_without_armoury_degrades_visibly() -> None:
    """No armoury means no save — but every ignored item is reported."""
    archers = load_unit("high-elf-realms", "elven-archers")
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    result = shoot_unit(archers, spearmen, shooters=3, weapon=load_weapon("longbow"))
    assert result.save_target is None
    assert any("Light Armour" in note for note in result.notes)
    assert any("Shield" in note for note in result.notes)


def test_defender_size_does_not_affect_wounds() -> None:
    """Wounds depend on the shooters, not on how many models receive them.

    Regression guard: 3 archers shooting 20 spearmen and 3 archers
    shooting 30 spearmen must produce the identical wound distribution.
    """
    archers = load_unit("high-elf-realms", "elven-archers")
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    longbow = load_weapon("longbow")
    twenty = spearmen.model_copy(update={"unit_size": {"min": 20, "max": 20}}, deep=True)
    thirty = spearmen.model_copy(update={"unit_size": {"min": 30, "max": 30}}, deep=True)

    vs_twenty = shoot_unit(archers, twenty, shooters=3, weapon=longbow, armoury=ARMOURY)
    vs_thirty = shoot_unit(archers, thirty, shooters=3, weapon=longbow, armoury=ARMOURY)

    assert vs_twenty.p_unsaved == vs_thirty.p_unsaved
    assert vs_twenty.distribution == vs_thirty.distribution
    assert vs_twenty.expected_wounds == vs_thirty.expected_wounds


def test_shoot_caps_casualties_at_target_size() -> None:
    """A volley cannot remove more models than the unit contains.

    10 shots at p = 1/2 against a 2-model unit: the wound distribution
    keeps all 11 outcomes, but casualties collapse to 0, 1, or 2, with
    P(2) absorbing every outcome of 2+ wounds.
    """
    result = shoot(10, ballistic_skill=4, strength=3, toughness=3, targets=2)
    assert len(result.distribution) == 11
    assert len(result.casualties) == 3
    assert result.casualties[2] == pytest.approx(sum(result.distribution[2:]))
    assert sum(result.casualties) == pytest.approx(1.0)
    assert result.expected_casualties < result.expected_wounds


def test_shoot_casualties_equal_wounds_when_uncapped() -> None:
    """With no target size, casualties are exactly the wound distribution."""
    result = shoot(3, ballistic_skill=4, strength=3, toughness=3, armour_value=5)
    assert result.target_models is None
    assert result.casualties == result.distribution
    assert result.expected_casualties == pytest.approx(result.expected_wounds)


def test_shoot_rejects_negative_targets() -> None:
    """A negative target count is meaningless."""
    with pytest.raises(ValueError, match="targets must be >= 0"):
        shoot(3, ballistic_skill=4, strength=3, toughness=3, targets=-1)


def test_shoot_unit_caps_casualties_but_not_wounds() -> None:
    """``defenders`` bounds casualties while leaving the wound math intact.

    30 archers into 5 spearmen: the wound distribution is unbounded over
    30 shots, but the spearmen unit can lose at most 5 models.
    """
    archers = load_unit("high-elf-realms", "elven-archers")
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    result = shoot_unit(
        archers, spearmen, shooters=30, weapon=load_weapon("longbow"), armoury=ARMOURY, defenders=5
    )
    assert result.target_models == 5
    assert len(result.distribution) == 31
    assert len(result.casualties) == 6
    assert result.expected_casualties < result.expected_wounds
    assert any("panic test at 25%" in note for note in result.notes)


def test_shoot_folds_wounds_into_multi_wound_models() -> None:
    """With Wounds 3, casualties are wounds // 3 — models, not wounds.

    6 shots produce a 0..6 wound distribution; folded by 3 it becomes a
    0..2 models-removed distribution, each bucket the sum of its three
    wound outcomes.
    """
    result = shoot(6, ballistic_skill=4, strength=3, toughness=3, wounds_per_model=3)
    d = result.distribution
    assert len(result.casualties) == 3  # 0, 1, 2 models from 0..6 wounds
    assert result.casualties[0] == pytest.approx(d[0] + d[1] + d[2])
    assert result.casualties[1] == pytest.approx(d[3] + d[4] + d[5])
    assert result.casualties[2] == pytest.approx(d[6])
    assert result.expected_casualties < result.expected_wounds  # 3 wounds per kill
    assert sum(result.casualties) == pytest.approx(1.0)


def test_shoot_rejects_non_positive_wounds_per_model() -> None:
    """A model with fewer than 1 Wound is meaningless."""
    with pytest.raises(ValueError, match="wounds_per_model must be >= 1"):
        shoot(3, ballistic_skill=4, strength=3, toughness=3, wounds_per_model=0)


def test_shoot_unit_folds_multi_wound_casualties_and_caps() -> None:
    """A W3 target: wounds fold into slain models, then cap at the unit size.

    30 archers into 5 Wounds-3 models: casualties are models removed (three
    wounds each), capped at 5, and fewer than the wounds inflicted. The
    old "carry-over not modelled" disclaimer is gone; the panic note stays.
    """
    archers = load_unit("high-elf-realms", "elven-archers")
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    multi_wound = spearmen.model_copy(deep=True)
    object.__setattr__(multi_wound.profiles[0], "wounds", 3)
    result = shoot_unit(
        archers,
        multi_wound,
        shooters=30,
        weapon=load_weapon("longbow"),
        armoury=ARMOURY,
        defenders=5,
    )
    assert result.target_models == 5  # cap now applied
    assert len(result.casualties) == 6  # 0..5 models
    assert result.expected_casualties < result.expected_wounds
    assert sum(result.casualties) == pytest.approx(1.0)
    assert any("panic" in note for note in result.notes)
    assert not any("carry-over" in note for note in result.notes)


def test_shoot_unit_warbow_uses_wielders_strength() -> None:
    """End-to-end from data files: Lothern Sea Guard shoot Elven Spearmen.

    The warbow's printed Strength is "S", so shots resolve at the Sea
    Guard's S3 vs T3: wound on 4+, same 2/9 per-shot chain as the longbow
    golden test (spearmen save on 5+, no AP).
    """
    sea_guard = load_unit("high-elf-realms", "lothern-sea-guard")
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    result = shoot_unit(
        sea_guard, spearmen, shooters=3, weapon=load_weapon("warbow"), armoury=ARMOURY
    )
    assert result.hit_target == 3  # BS 4
    assert result.wound_target == 4  # wielder's S3 vs T3
    assert result.expected_wounds == pytest.approx(2 / 3)


def test_shoot_unit_rejects_wielder_strength_weapon_without_strength() -> None:
    """A "Strength: S" weapon cannot resolve if the wielder has no S."""
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    strengthless = spearmen.model_copy(deep=True)
    object.__setattr__(strengthless.profiles[0], "strength", None)
    with pytest.raises(ValueError, match="wielder's Strength"):
        shoot_unit(strengthless, spearmen, shooters=1, weapon=load_weapon("warbow"))


def test_shoot_unit_rejects_pure_melee_weapon() -> None:
    """A weapon with no missile profile cannot shoot."""
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    with pytest.raises(ValueError, match="missile profile"):
        shoot_unit(spearmen, spearmen, shooters=1, weapon=load_weapon("hand-weapon"))


def test_shoot_unit_rejects_missing_ballistic_skill() -> None:
    """A unit whose profile has BS "-" cannot shoot."""
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    crewless = spearmen.model_copy(deep=True)
    object.__setattr__(crewless.profiles[0], "ballistic_skill", None)
    with pytest.raises(ValueError, match="Ballistic Skill"):
        shoot_unit(crewless, spearmen, shooters=1, weapon=load_weapon("longbow"))


def _killing_blow_double() -> Transform:
    def escalate(face: int, profile: AttackProfile) -> AttackProfile:
        if face != 6:
            return profile
        return replace(
            profile, save_target=RollState.IMPOSSIBLE, unsaved_outcome=Outcome.INSTANT_KILL
        )

    return Transform(stage=Stage.ROLL_TO_WOUND, on_success=escalate)


def test_shoot_instant_kills_remove_multi_wound_models_outright() -> None:
    """Two attacks can only fell both Wounds-3 models via two kills.

    Hit 3+, wound 4+, save 5+ with the kill double: p_kill = 1/9 per
    attack and plain wounds (at most 2 < 3) fell nobody, so casualties
    are Binomial(2, 1/9): P(2) = 1/81.
    """
    result = shoot(
        2,
        ballistic_skill=4,
        strength=3,
        toughness=3,
        armour_value=5,
        wounds_per_model=3,
        targets=2,
        transforms=[_killing_blow_double()],
    )
    assert result.casualties[2] == pytest.approx(1 / 81)
    assert result.casualties[1] == pytest.approx(2 * (1 / 9) * (8 / 9))
    assert result.casualties[0] == pytest.approx((8 / 9) ** 2)
    assert sum(result.casualties) == pytest.approx(1.0)


def test_shoot_instant_kills_match_the_spike_distribution() -> None:
    """12 attacks vs 2 Wounds-3 models reproduce the class-aware spike.

    Spike values (verified there against Monte Carlo): P(0)=0.165,
    P(1)=0.342, P(2)=0.493.
    """
    result = shoot(
        12,
        ballistic_skill=4,
        strength=3,
        toughness=3,
        armour_value=5,
        wounds_per_model=3,
        targets=2,
        transforms=[_killing_blow_double()],
    )
    assert result.casualties[0] == pytest.approx(0.165, abs=5e-4)
    assert result.casualties[1] == pytest.approx(0.342, abs=5e-4)
    assert result.casualties[2] == pytest.approx(0.493, abs=5e-4)
    assert sum(result.casualties) == pytest.approx(1.0)
    assert sum(result.distribution) == pytest.approx(1.0)


def test_remove_casualties_with_no_kill_mass_matches_binomial_path() -> None:
    """The class-aware fold degenerates to binomial -> group -> cap."""
    from avelorn.core.dice import binomial_distribution, cap_distribution, group_distribution

    p = 2 / 9
    distribution, casualties = _remove_casualties(
        10, p_wound_only=p, p_kill=0.0, wounds_per_model=3, targets=2
    )
    expected_distribution = binomial_distribution(10, p)
    expected_casualties = cap_distribution(group_distribution(expected_distribution, 3), 2)
    assert distribution == pytest.approx(expected_distribution)
    assert casualties == pytest.approx(expected_casualties)
