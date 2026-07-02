"""Rule compilation tests: printed names to transforms, from real data."""

from fractions import Fraction
from pathlib import Path

import pytest

from avelorn.core.loading import load_yaml, load_yaml_dir
from avelorn.tow.combat.attack import AttackProfile, RollState, resolve_attack
from avelorn.tow.combat.rules import compile_rules, resolve_rule
from avelorn.tow.combat.shooting import shoot_unit
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon

DATA_DIR = Path(__file__).parents[3] / "data"

RULES = {r.name: r for r in load_yaml_dir(DATA_DIR / "tow/rules", Rule)}
ARMOURY = {a.name: a for a in load_yaml_dir(DATA_DIR / "tow/armour", Armour)}


def test_resolve_exact_name() -> None:
    """A printed name matching a rule name resolves without a parameter."""
    resolved = resolve_rule("Killing Blow", RULES)
    assert resolved is not None
    assert resolved.rule.id == "killing-blow"
    assert resolved.parameter is None


def test_resolve_parameterised_name() -> None:
    """A bracketed number matches the rule filed under the (X) placeholder."""
    resolved = resolve_rule("Armour Bane (1)", RULES)
    assert resolved is not None
    assert resolved.rule.id == "armour-bane"
    assert resolved.parameter == 1


def test_resolve_unknown_name() -> None:
    """A name matching nothing resolves to None."""
    assert resolve_rule("Volley Fire", RULES) is None


def test_compile_armour_bane_from_data_reproduces_the_golden() -> None:
    """The data-compiled Armour Bane transform yields the 13/54 golden.

    Hit 3+, wound 4+, save 5+: on a natural 6 To Wound the save worsens
    to 6+, so p = 2/3 * (2/6 * 2/3 + 1/6 * 5/6) = 13/54 — previously
    proven by a hand-written test double, now driven by the rule file.
    """
    transforms, unfactored = compile_rules(["Armour Bane (1)"], RULES)
    assert unfactored == []
    profile = AttackProfile(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    assert resolve_attack(profile, transforms).p_unsaved == Fraction(13, 54)


def test_compile_effectless_rule_stays_unfactored() -> None:
    """A resolved rule with no effects is recognised but not factored."""
    transforms, unfactored = compile_rules(["Killing Blow"], RULES)
    assert transforms == []
    assert unfactored == ["Killing Blow"]


def test_compile_parameter_placeholder_without_value_stays_unfactored() -> None:
    """The X placeholder needs a bracketed number in the printed name."""
    rule = RULES["Armour Bane (X)"]
    transforms, unfactored = compile_rules(["Armour Bane (X)"], RULES)
    assert rule.effects and transforms == []
    assert unfactored == ["Armour Bane (X)"]


def _load_unit(slug: str) -> Unit:
    return load_yaml(DATA_DIR / f"tow/armies/high-elf-realms/units/{slug}.yaml", Unit)


def _load_weapon(slug: str) -> Weapon:
    return load_yaml(DATA_DIR / f"tow/weapons/{slug}.yaml", Weapon)


def test_shoot_unit_factors_armour_bane_from_data() -> None:
    """End to end: the Longbow's Armour Bane (1) changes the math.

    Archers vs spearmen (5+ save): per-shot unsaved moves from 2/9 to
    13/54, the Armour Bane note disappears, and Volley Fire stays noted.
    """
    result = shoot_unit(
        _load_unit("elven-archers"),
        _load_unit("elven-spearmen"),
        shooters=3,
        weapon=_load_weapon("longbow"),
        armoury=ARMOURY,
        rules=RULES,
    )
    assert result.p_unsaved == pytest.approx(13 / 54)
    assert not any("Armour Bane" in note for note in result.notes)
    assert any("Volley Fire" in note for note in result.notes)


def test_shoot_unit_without_rules_is_unchanged() -> None:
    """No rules registry: every weapon rule stays noted, math unchanged."""
    result = shoot_unit(
        _load_unit("elven-archers"),
        _load_unit("elven-spearmen"),
        shooters=3,
        weapon=_load_weapon("longbow"),
        armoury=ARMOURY,
    )
    assert result.p_unsaved == pytest.approx(2 / 9)
    assert any("Armour Bane (1)" in note for note in result.notes)
