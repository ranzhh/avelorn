"""Rule compilation tests: printed names to transforms, from real data."""

from fractions import Fraction

import pytest

from avelorn.tow.combat.attack import AttackProfile, HitRoll, RollState, resolve_attack
from avelorn.tow.combat.context import EngagementContext
from avelorn.tow.combat.contingent import Contingent
from avelorn.tow.combat.rules import _condition_applies, compile_rules, printed_rule
from avelorn.tow.combat.shooting import shoot_unit
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.rule import ArmourPiercingEffect
from avelorn.tow.schema.unit import Unit

REPO = TOWRepository()


def _fielded(unit: Unit, models: int) -> Contingent:
    # Field at the printed, optionless loadout, with the real registries.
    return Contingent.field(
        unit, models, weapons=REPO.weapons, armoury=REPO.armoury, rules=REPO.rules
    )


def test_printed_rule_exact_name_is_the_entry_itself() -> None:
    """A printed name matching an entry name returns that entry, unchanged."""
    assert printed_rule("Killing Blow", REPO.rules) is REPO.rules["killing-blow"]


def test_printed_rule_substitutes_the_parameter() -> None:
    """A bracketed number matches the (X) entry, returned as printed.

    The copy carries the printed name and the parameter substituted into
    its effects — the rule as the unit prints it, not as it is filed.
    """
    rule = printed_rule("Armour Bane (1)", REPO.rules)
    assert rule is not None
    assert rule.id == "armour-bane"
    assert rule.name == "Armour Bane (1)"
    effect = rule.effects[0]
    assert isinstance(effect, ArmourPiercingEffect)
    assert effect.amount == 1
    # The filed entry is untouched: the placeholder still reads "X".
    filed = REPO.rules["armour-bane"].effects[0]
    assert isinstance(filed, ArmourPiercingEffect)
    assert filed.amount == "X"


def test_printed_rule_unknown_name() -> None:
    """A name matching nothing resolves to None."""
    assert printed_rule("Volley Fire", REPO.rules) is None


def test_compile_armour_bane_from_data_reproduces_the_golden() -> None:
    """The data-compiled Armour Bane transform yields the 13/54 golden.

    Hit 3+, wound 4+, save 5+: on a natural 6 To Wound the save worsens
    to 6+, so p = 2/3 * (2/6 * 2/3 + 1/6 * 5/6) = 13/54 — previously
    proven by a hand-written test double, now driven by the rule file.
    """
    transforms, unfactored = compile_rules(["Armour Bane (1)"], REPO.rules)
    assert unfactored == []
    profile = AttackProfile(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    assert resolve_attack(profile, transforms, hit_roll=HitRoll.SHOOTING).p_unsaved == Fraction(
        13, 54
    )


def test_compile_effectless_rule_stays_unfactored() -> None:
    """A resolved rule with no effects is recognised but not factored."""
    transforms, unfactored = compile_rules(["Killing Blow"], REPO.rules)
    assert transforms == []
    assert unfactored == ["Killing Blow"]


def test_compile_parameter_placeholder_without_value_stays_unfactored() -> None:
    """The X placeholder needs a bracketed number in the printed name."""
    rule = REPO.rules["armour-bane"]
    transforms, unfactored = compile_rules(["Armour Bane (X)"], REPO.rules)
    assert rule.effects and transforms == []
    assert unfactored == ["Armour Bane (X)"]


def test_shoot_unit_factors_armour_bane_from_data() -> None:
    """End to end: the Longbow's Armour Bane (1) changes the math.

    Archers vs spearmen (5+ save): per-shot unsaved moves from 2/9 to
    13/54, the Armour Bane note disappears, and Volley Fire stays noted.
    """
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3),
        _fielded(REPO.units["elven-spearmen"], 10),
        weapon=REPO.weapons["longbow"],
        armoury=REPO.armoury,
        rules=REPO.rules,
    )
    assert result.p_unsaved == pytest.approx(13 / 54)
    assert not any("Armour Bane" in note for note in result.notes)
    assert any("Volley Fire" in note for note in result.notes)


def test_shoot_unit_without_rules_is_unchanged() -> None:
    """No rules registry: every weapon rule stays noted, math unchanged."""
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3),
        _fielded(REPO.units["elven-spearmen"], 10),
        weapon=REPO.weapons["longbow"],
        armoury=REPO.armoury,
    )
    assert result.p_unsaved == pytest.approx(2 / 9)
    assert any("Armour Bane (1)" in note for note in result.notes)


def test_long_range_penalty_applies_from_data() -> None:
    """Beyond half range the To Hit target worsens by the printed -1.

    Archers at 20" with 30" longbows: 20 > 15, so hit 4+ instead of 3+;
    with Armour Bane live, p = 1/2 * (2/6 * 2/3 + 1/6 * 5/6) = 13/72.
    """
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3),
        _fielded(REPO.units["elven-spearmen"], 10),
        weapon=REPO.weapons["longbow"],
        armoury=REPO.armoury,
        rules=REPO.rules,
        context=EngagementContext(moved=False, distance=20),
    )
    assert result.p_unsaved == pytest.approx(13 / 72)
    assert not any("core rule" in note for note in result.notes)


def test_condition_false_applies_no_penalty_and_no_note() -> None:
    """Within half range and stationary: no modifier, and no note either.

    A rule whose condition evaluates False is honoured by not applying.
    """
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3),
        _fielded(REPO.units["elven-spearmen"], 10),
        weapon=REPO.weapons["longbow"],
        armoury=REPO.armoury,
        rules=REPO.rules,
        context=EngagementContext(moved=False, distance=10),
    )
    assert result.p_unsaved == pytest.approx(13 / 54)
    assert not any("core rule" in note for note in result.notes)


def test_unknown_context_leaves_core_rules_unfactored() -> None:
    """Without an engagement context the phase rules cannot be evaluated."""
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3),
        _fielded(REPO.units["elven-spearmen"], 10),
        weapon=REPO.weapons["longbow"],
        armoury=REPO.armoury,
        rules=REPO.rules,
    )
    assert result.p_unsaved == pytest.approx(13 / 54)
    assert any("core rule not factored: Firing at Long Range" in n for n in result.notes)
    assert any("core rule not factored: Moving and Shooting" in n for n in result.notes)


def test_both_penalties_stack() -> None:
    """Moved and at long range: -1 and -1, hit 5+."""
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3),
        _fielded(REPO.units["elven-spearmen"], 10),
        weapon=REPO.weapons["longbow"],
        armoury=REPO.armoury,
        rules=REPO.rules,
        context=EngagementContext(moved=True, distance=20),
    )
    assert result.hit_target == 5


def test_move_in_or_stay_out_is_a_wash() -> None:
    """Warbows at 15": staying (long range -1) equals closing (moved -1).

    Warbow range is 24", so 15" is beyond half range; closing inside 12"
    removes that penalty but "moved for any reason during this turn"
    imposes its own -1. Both plans hit on 4+ with identical
    distributions — computed from the printed rules, not judgement.
    """
    sea_guard = REPO.units["lothern-sea-guard"]
    spearmen = REPO.units["elven-spearmen"]
    warbow = REPO.weapons["warbow"]
    stay = shoot_unit(
        _fielded(sea_guard, 10),
        _fielded(spearmen, 10),
        warbow,
        armoury=REPO.armoury,
        rules=REPO.rules,
        context=EngagementContext(moved=False, distance=15),
    )
    move_in = shoot_unit(
        _fielded(sea_guard, 10),
        _fielded(spearmen, 10),
        warbow,
        armoury=REPO.armoury,
        rules=REPO.rules,
        context=EngagementContext(moved=True, distance=12),
    )
    assert stay.hit_target == move_in.hit_target == 4
    assert stay.p_unsaved == pytest.approx(move_in.p_unsaved)
    assert stay.casualties == pytest.approx(move_in.casualties)


def test_every_condition_is_consulted() -> None:
    """Each Condition, when asked, must gate on the engagement facts.

    Drift guard: a condition asked for but absent from the facts must
    make the rule unevaluatable (None), never be silently ignored.
    Iterates the vocabulary so new members are covered automatically.
    """
    from avelorn.tow.schema.rule import Condition

    for condition in Condition:
        when = {condition: True}
        assert _condition_applies(when, {}) is None, condition
        assert _condition_applies(when, {condition: True}) is True, condition
        assert _condition_applies(when, {condition: False}) is False, condition


def test_conjunctive_condition_with_known_false_member_does_not_apply() -> None:
    """One known-False conjunct settles it, even beside an unknown one.

    {moved: True, at_long_range: True} against a stationary unit at an
    unknown distance definitely does not apply — silent no-op, not
    "cannot be evaluated".
    """
    from avelorn.tow.schema.rule import Condition

    moved, ranged = Condition.MOVED, Condition.AT_LONG_RANGE
    both = {moved: True, ranged: True}
    assert _condition_applies(both, {moved: False, ranged: None}) is False
    assert _condition_applies(both, {moved: True, ranged: None}) is None
    assert _condition_applies(both, {moved: True, ranged: True}) is True
