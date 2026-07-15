"""Rule compilation tests: printed names to transforms, from real data."""

from fractions import Fraction
from typing import Literal

import pytest

from avelorn.tow.combat.attack import AttackProfile, RollState, resolve_attack
from avelorn.tow.combat.context import EngagementContext
from avelorn.tow.combat.contingent import Contingent
from avelorn.tow.combat.rules import (
    _condition_applies,
    compile_rules,
    effective_characteristic,
    printed_rule,
)
from avelorn.tow.combat.shooting import shoot_unit
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.rule import (
    Condition,
    ModifierEffect,
    NaturalRoll,
    Rule,
    RuleEffect,
)
from avelorn.tow.schema.stage import Stage
from avelorn.tow.schema.unit import Characteristic, Unit

REPO = TOWRepository()

# The shooting chapter's rules in force, built directly: these tests
# exercise the combat layer, which must not depend on game assembly.
IN_FORCE = {r.name: r for r in REPO.rules.values() if r.category == Phase.SHOOTING and r.effects}


def _fielded(unit: Unit, models: int) -> Contingent:
    # Field at the printed, optionless loadout, with the real registries.
    return Contingent.field(
        unit, models, weapons=REPO.weapons, armoury=REPO.armoury, rules=REPO.rules
    )


def _one_rule(effect: RuleEffect) -> dict[str, Rule]:
    # One doctored rule, resolved as printed, to compile a single effect
    # shape the data/ files do not exercise yet.
    rule = Rule(id="doctored", name="Doctored", paragraphs=["…"], effects=[effect])
    return {rule.name: rule}


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
    assert isinstance(effect, ModifierEffect)
    assert effect.then == {"armour-piercing": 1}
    # The filed entry is untouched: the placeholder still reads "X".
    filed = REPO.rules["armour-bane"].effects[0]
    assert isinstance(filed, ModifierEffect)
    assert filed.then == {"armour-piercing": "X"}


def test_printed_rule_unknown_name() -> None:
    """A name matching nothing resolves to None."""
    assert printed_rule("Volley Fire", REPO.rules) is None


def test_compile_armour_bane_from_data_reproduces_the_golden() -> None:
    """The data-compiled Armour Bane transform yields the 13/54 golden.

    Hit 3+, wound 4+, save 5+: on a natural 6 To Wound the save worsens
    to 6+, so p = 2/3 * (2/6 * 2/3 + 1/6 * 5/6) = 13/54 — previously
    proven by a hand-written test double, now driven by the rule file.
    """
    index = _fielded(REPO.units["elven-archers"], 1).loadout.weapon_rules
    transforms, unfactored = compile_rules(["Armour Bane (1)"], index)
    assert unfactored == []
    profile = AttackProfile.shooting(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    assert resolve_attack(profile, transforms).p_unsaved == Fraction(13, 54)


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


def test_unconditional_armour_piercing_modifier_factors() -> None:
    """An AP change with no trigger lands before every save roll.

    The generic modifier path expresses what the old per-kind compiler
    refused (an AP improvement not gated on a die): hit 3+, wound 4+,
    save 5+ worsened to 6+ on every attack, p = 2/3 * 1/2 * 5/6 = 5/18.
    """
    rules = _one_rule(ModifierEffect(then={"armour-piercing": 1}))
    transforms, unfactored = compile_rules(["Doctored"], rules)
    assert unfactored == []
    profile = AttackProfile.shooting(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    assert resolve_attack(profile, transforms).p_unsaved == Fraction(5, 18)


def test_trigger_at_or_after_the_landing_stage_stays_unfactored() -> None:
    """A die can only shape rolls still to come.

    A To Hit change triggered by the To Wound die would land on a roll
    already made; the rule is honestly unfactored, never a silent no-op.
    """
    effect = ModifierEffect(
        when={"natural": NaturalRoll(face=6, roll=Stage.ROLL_TO_WOUND)}, then={"to-hit": 1}
    )
    transforms, unfactored = compile_rules(["Doctored"], _one_rule(effect))
    assert transforms == []
    assert unfactored == ["Doctored"]


def test_shoot_unit_factors_armour_bane_from_data() -> None:
    """End to end: the Longbow's Armour Bane (1) changes the math.

    Archers vs spearmen (5+ save): per-shot unsaved moves from 2/9 to
    13/54, the Armour Bane note disappears, and Volley Fire stays noted.
    """
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3),
        _fielded(REPO.units["elven-spearmen"], 10),
        weapon=REPO.weapons["longbow"],
        phase_rules=IN_FORCE,
    )
    assert result.p_unsaved == pytest.approx(13 / 54)
    assert not any("Armour Bane" in note for note in result.notes)
    assert any("Volley Fire" in note for note in result.notes)


def test_weapon_rules_factor_from_the_loadout_alone() -> None:
    """No registry at the action: the weapon's rules ride with the unit.

    Fielding resolved the Longbow's Armour Bane (1), so the volley
    factors it (2/9 -> 13/54 per shot) with no ``rules=`` passed at all;
    Volley Fire has no entry and stays noted. Only the shooting phase's
    own chapter rules still come from the registry.
    """
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3),
        _fielded(REPO.units["elven-spearmen"], 10),
        weapon=REPO.weapons["longbow"],
    )
    assert result.p_unsaved == pytest.approx(13 / 54)
    assert not any("Armour Bane" in note for note in result.notes)
    assert any("Volley Fire" in note for note in result.notes)


def test_long_range_penalty_applies_from_data() -> None:
    """Beyond half range the To Hit target worsens by the printed -1.

    Archers at 20" with 30" longbows: 20 > 15, so hit 4+ instead of 3+;
    with Armour Bane live, p = 1/2 * (2/6 * 2/3 + 1/6 * 5/6) = 13/72.
    """
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3),
        _fielded(REPO.units["elven-spearmen"], 10),
        weapon=REPO.weapons["longbow"],
        phase_rules=IN_FORCE,
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
        phase_rules=IN_FORCE,
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
        phase_rules=IN_FORCE,
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
        phase_rules=IN_FORCE,
        context=EngagementContext(moved=True, distance=20),
    )
    assert result.hit_target == 5


def test_staying_still_volley_fires_while_the_to_hit_is_a_wash() -> None:
    """Warbows at 15": staying and closing hit alike, but staying volley fires.

    Warbow range is 24", so 15" is beyond half range; closing inside 12"
    removes that penalty but "moved for any reason during this turn"
    imposes its own -1 — so both plans hit on 4+ with the same per-shot
    chance. Staying still is not a wash, though: it lets the rear rank
    volley fire, so it looses more shots and fells more.
    """
    sea_guard = REPO.units["lothern-sea-guard"]
    spearmen = REPO.units["elven-spearmen"]
    warbow = REPO.weapons["warbow"]
    stay = shoot_unit(
        _fielded(sea_guard, 10),
        _fielded(spearmen, 10),
        warbow,
        phase_rules=IN_FORCE,
        context=EngagementContext(moved=False, distance=15),
    )
    move_in = shoot_unit(
        _fielded(sea_guard, 10),
        _fielded(spearmen, 10),
        warbow,
        phase_rules=IN_FORCE,
        context=EngagementContext(moved=True, distance=12),
    )
    assert stay.hit_target == move_in.hit_target == 4  # the To Hit is a wash
    assert stay.p_unsaved == pytest.approx(move_in.p_unsaved)  # per shot, identical
    assert stay.shots > move_in.shots  # but staying volley fires
    assert stay.expected_casualties > move_in.expected_casualties


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


def test_every_modifier_kind_declares_its_roll() -> None:
    """Each modifier kind maps onto a roll the attack profile carries.

    Drift guard for the table's exhaustiveness: a kind joining the
    vocabulary must declare which roll it changes, and the profile must
    carry a target for that roll's stage. Both sides are introspected,
    so new members are covered automatically.
    """
    from typing import get_args

    from avelorn.tow.combat.rules import _ROLLS
    from avelorn.tow.schema.rule import ModifierKind

    profile = AttackProfile.shooting(hit_target=4, wound_target=4, save_target=4, ward_target=4)
    for kind in get_args(ModifierKind):
        assert kind in _ROLLS, kind
        profile.target(_ROLLS[kind].stage)  # KeyError if the stage rolls no target


def test_armour_bane_two_leaves_no_save_at_all() -> None:
    """Armour Bane (2) pushes a 5+ save past 6+: the save is not taken.

    What the moved target means is the roll's own knowledge — a save
    worse than 6+ cannot be attempted; the modifier only moves the
    number. Hit 3+, wound 4+, save 5+:
    p = 2/3 * (2/6 * 4/6 + 1/6 * 1) = 7/27.
    """
    bane = printed_rule("Armour Bane (2)", REPO.rules)
    assert bane is not None
    transforms, unfactored = compile_rules(["Armour Bane (2)"], {bane.name: bane})
    assert unfactored == []
    profile = AttackProfile.shooting(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    assert resolve_attack(profile, transforms).p_unsaved == Fraction(7, 27)


# --- effective_characteristic: the characteristic-read query ---


def _initiative_rule(
    amount: int | Literal["X"] = 1,
    maximum: int | None = 10,
    when: dict[Condition | Literal["natural"], bool | NaturalRoll] | None = None,
    characteristic: Characteristic = Characteristic.INITIATIVE,
) -> Rule:
    effect = ModifierEffect(when=when, then={characteristic: amount}, maximum=maximum)
    return Rule(id="doctored", name="Doctored (X)", paragraphs=["…"], effects=[effect])


def test_effective_characteristic_applies_a_modifier() -> None:
    """An unconditional +1 lands on the read; the rule is factored."""
    result = effective_characteristic(4, Characteristic.INITIATIVE, [_initiative_rule()])
    assert result.value == 5
    assert result.factored == ("Doctored (X)",)
    assert result.unfactored == ()


def test_effective_characteristic_honours_the_printed_maximum() -> None:
    """The modified value stops at the effect's printed ceiling."""
    result = effective_characteristic(
        9, Characteristic.INITIATIVE, [_initiative_rule(amount=3, maximum=10)]
    )
    assert result.value == 10


def test_effective_characteristic_unknown_condition_is_unfactored() -> None:
    """A modifier gated on an unanswered fact does not apply, and is reported."""
    rule = _initiative_rule(when={Condition.FIRST_ROUND_OF_COMBAT: True})
    result = effective_characteristic(4, Characteristic.INITIATIVE, [rule], {})
    assert result.value == 4
    assert result.factored == ()
    assert result.unfactored == ("Doctored (X)",)


def test_effective_characteristic_false_condition_is_honoured() -> None:
    """A condition answered False applies nothing — factored, not reported."""
    rule = _initiative_rule(when={Condition.FIRST_ROUND_OF_COMBAT: True})
    result = effective_characteristic(
        4, Characteristic.INITIATIVE, [rule], {Condition.FIRST_ROUND_OF_COMBAT: False}
    )
    assert result.value == 4
    assert result.factored == ("Doctored (X)",)
    assert result.unfactored == ()


def test_effective_characteristic_unbound_parameter_is_unfactored() -> None:
    """An unsubstituted X cannot apply; the rule is reported instead."""
    result = effective_characteristic(4, Characteristic.INITIATIVE, [_initiative_rule(amount="X")])
    assert result.value == 4
    assert result.unfactored == ("Doctored (X)",)


def test_effective_characteristic_ignores_other_characteristics() -> None:
    """A modifier naming another characteristic is not this query's business."""
    rule = _initiative_rule(characteristic=Characteristic.STRENGTH)
    result = effective_characteristic(4, Characteristic.INITIATIVE, [rule])
    assert result.value == 4
    assert result.factored == ()
    assert result.unfactored == ()
