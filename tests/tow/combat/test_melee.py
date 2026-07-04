"""Close-combat strike tests, golden values hand-computed from the charts."""

from pathlib import Path

import pytest

from avelorn.core.dice import binomial_distribution, expected_value
from avelorn.core.loading import load_yaml, load_yaml_dir
from avelorn.tow.combat.melee import fight, strike, strike_unit
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.unit import Characteristic, Unit
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


def test_strike_golden_no_save() -> None:
    """WS4 vs WS4 (4+), S4 vs T4 (4+), no armour: p_unsaved = 1/4."""
    result = strike(3, weapon_skill=4, target_weapon_skill=4, strength=4, toughness=4)
    assert result.hit_target == 4
    assert result.wound_target == 4
    assert result.save_target is None
    assert result.p_hit == pytest.approx(0.5)
    assert result.p_wound == pytest.approx(0.5)
    assert result.p_unsaved == pytest.approx(0.25)
    assert result.distribution == pytest.approx(binomial_distribution(3, 0.25))


def test_strike_golden_with_armour() -> None:
    """WS6 vs WS3 (3+), S5 vs T3 (2+), 5+ save: p_unsaved = 10/27."""
    result = strike(
        6, weapon_skill=6, target_weapon_skill=3, strength=5, toughness=3, armour_value=5
    )
    assert result.hit_target == 3
    assert result.wound_target == 2
    assert result.save_target == 5
    assert result.p_unsaved == pytest.approx(10 / 27)


def test_strike_hit_penalty_past_the_chart_still_hits_on_a_six() -> None:
    """A -3 To Hit modifier pushes a 4+ to 7+; only a natural 6 lands (1/6)."""
    result = strike(
        1,
        weapon_skill=4,
        target_weapon_skill=4,
        strength=10,
        toughness=1,
        hit_modifier=-3,
    )
    assert result.hit_target == 7
    assert result.p_hit == pytest.approx(1 / 6)
    assert result.p_unsaved == pytest.approx(1 / 6 * 5 / 6)


def test_strike_caps_casualties_at_target_size() -> None:
    """Casualties never exceed the defending unit's model count."""
    result = strike(20, weapon_skill=6, target_weapon_skill=2, strength=6, toughness=2, targets=3)
    assert len(result.casualties) == 4  # 0..3
    assert sum(result.casualties) == pytest.approx(1.0)


def test_strike_rejects_negative_attacks() -> None:
    """A negative attack count is a programming error, not a silent zero."""
    with pytest.raises(ValueError, match="attacks must be >= 0"):
        strike(-1, weapon_skill=4, target_weapon_skill=4, strength=4, toughness=4)


# --- strike_unit: end-to-end from the data/ tree ---


def test_strike_unit_spearmen_vs_spearmen() -> None:
    """5 Elven Spearmen fight Elven Spearmen with thrusting spears.

    WS4 vs WS4 (4+), thrusting spear at S (S3) vs T3 (4+), and the target's
    light armour (6+) + shield (+1) give a 5+ save; A1 each -> 5 attacks.
    p_unsaved = 1/2 * 1/2 * 4/6 = 1/6.
    """
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    result = strike_unit(
        spearmen, spearmen, fighters=5, weapon=load_weapon("thrusting-spear"), armoury=ARMOURY
    )
    assert result.attacks == 5  # 5 fighters * A1
    assert result.hit_target == 4
    assert result.wound_target == 4
    assert result.save_target == 5
    assert result.p_unsaved == pytest.approx(1 / 6)
    assert any("Fight In Extra Rank" in note for note in result.notes)  # weapon rule unfactored
    assert any("Valour of Ages" in note for note in result.notes)  # unit special rule
    assert any("thrusting spear" in note.lower() for note in result.notes)  # weapon notes


def test_strike_unit_attacks_scale_with_the_attacks_characteristic() -> None:
    """Each fighter makes its full Attacks: A2 over 5 fighters is 10 attacks."""
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    two_attacks = spearmen.model_copy(deep=True)
    two_attacks.profiles[0].characteristics[Characteristic.ATTACKS] = 2
    result = strike_unit(
        two_attacks, spearmen, fighters=5, weapon=load_weapon("thrusting-spear"), armoury=ARMOURY
    )
    assert result.attacks == 10


def test_strike_unit_without_armoury_degrades_visibly() -> None:
    """No armoury: the defender's armour is unresolved and reported, not guessed."""
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    result = strike_unit(spearmen, spearmen, fighters=5, weapon=load_weapon("thrusting-spear"))
    assert result.save_target is None
    assert any("Light Armour" in note for note in result.notes)


def test_strike_unit_rejects_a_missile_only_weapon() -> None:
    """A weapon with no Combat profile cannot be used to fight."""
    archers = load_unit("high-elf-realms", "elven-archers")
    with pytest.raises(ValueError, match="no Combat profile"):
        strike_unit(archers, archers, fighters=5, weapon=load_weapon("longbow"))


# --- fight(): one bilateral round with Initiative-ordered coupling ---


def _higher_initiative(unit: Unit, value: int = 10) -> Unit:
    """A copy of ``unit`` with its rank-and-file Initiative raised.

    Returns:
        The modified unit (so it strikes before an unmodified copy).
    """
    faster = unit.model_copy(deep=True)
    faster.profiles[0].characteristics[Characteristic.INITIATIVE] = value
    return faster


def test_fight_equal_initiative_is_simultaneous() -> None:
    """Same Initiative: both strike at full strength, no reduction.

    Spearman vs spearman (both I4), 1 fighter each: each takes the same
    single-attack casualty distribution, p_unsaved = 1/6.
    """
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    spear = load_weapon("thrusting-spear")
    result = fight(spearmen, 1, spear, spearmen, 1, spear, armoury=ARMOURY)
    assert result.first_striker is None
    assert result.a_casualties[1] == pytest.approx(1 / 6)
    assert result.b_casualties[1] == pytest.approx(1 / 6)


def test_fight_higher_initiative_strikes_first_and_takes_less() -> None:
    """A strikes first (I10 vs I4); B's survivors strike back with fewer models.

    1 vs 1: A's blow removes B on 1/6, so B swings back only when it
    survived (5/6) and then removes A on 1/6 -> A falls on 5/36. B, hit at
    full strength, falls on 1/6.
    """
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    spear = load_weapon("thrusting-spear")
    result = fight(_higher_initiative(spearmen), 1, spear, spearmen, 1, spear, armoury=ARMOURY)
    assert result.first_striker == "a"
    assert result.b_casualties[1] == pytest.approx(1 / 6)  # A full-strength
    assert result.a_casualties[1] == pytest.approx(5 / 36)  # B struck back reduced


def test_fight_coupling_reduces_the_return_strike() -> None:
    """Striking first strictly lowers the expected return damage taken.

    A (I10) vs B (I4), 5 each: some B models die before swinging, so the
    casualties A suffers are fewer than a full-strength B strike would deal.
    """
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    spear = load_weapon("thrusting-spear")
    result = fight(_higher_initiative(spearmen), 5, spear, spearmen, 5, spear, armoury=ARMOURY)
    full_strength = strike_unit(spearmen, spearmen, 5, spear, armoury=ARMOURY, defenders=5)
    assert expected_value(result.a_casualties) < expected_value(full_strength.casualties)
    assert any("Fight In Extra Rank" in note for note in result.notes)


def test_fight_rejects_negative_fighters() -> None:
    """A negative fighter count is a programming error, not a silent zero."""
    spearmen = load_unit("high-elf-realms", "elven-spearmen")
    spear = load_weapon("thrusting-spear")
    with pytest.raises(ValueError, match="fighter counts must be >= 0"):
        fight(spearmen, -1, spear, spearmen, 5, spear, armoury=ARMOURY)
