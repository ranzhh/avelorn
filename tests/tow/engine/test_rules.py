"""Rule compilation tests: printed names to transforms, from real data."""

from fractions import Fraction
from typing import Literal

import pytest

from avelorn.tow.contingent import Contingent, Movement
from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.attack import AttackProfile, RollState, resolve_attack
from avelorn.tow.engine.rules import (
    ArmourFacts,
    AttackFacts,
    ChargeEvent,
    CombatFacts,
    EffectiveValue,
    GateContext,
    MovementFacts,
    ShootingFacts,
    WeaponFacts,
    _gate_applies,
    attack_marks,
    compile_rules,
    effective_armour_value,
    effective_characteristic,
    effective_combat_result_bonus,
    effective_fighting_ranks,
    effective_rerolls,
    effective_supporting_ranks,
    effective_ward_target,
    printed_rule,
)
from avelorn.tow.phases.shooting import shoot_unit
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.rule import (
    ArmourGate,
    AttackKind,
    AttackMarkEffect,
    AttackMarks,
    ChargeGate,
    ModifierEffect,
    NaturalRoll,
    Quantity,
    RollResult,
    Rule,
    RuleEffect,
    When,
)
from avelorn.tow.schema.stage import Side, Stage
from avelorn.tow.schema.unit import Characteristic, Unit
from avelorn.tow.schema.weapon import WeaponType

REPO = TOWRepository()

# The shooting chapter's rules in force, built directly: these tests
# exercise the combat layer, which must not depend on game assembly.
IN_FORCE = {r.name: r for r in REPO.rules.values() if r.category == Phase.SHOOTING and r.effects}


def _fielded(unit: Unit, models: int, *, moved: bool = False) -> Contingent:
    # Field at the printed, optionless loadout, with the real registries;
    # ``moved`` sets the unit's movement (stationary by default).
    base = Contingent.field(unit, models, data=REPO)
    return base.after(Movement.march()) if moved else base


def _one_rule(effect: RuleEffect) -> dict[str, Rule]:
    # One doctored rule, resolved as printed, to compile a single effect
    # shape the data/ files do not exercise yet.
    rule = Rule(id="doctored", name="Doctored", paragraphs=["…"], effects=[effect])
    return {rule.name: rule}


def test_printed_rule_exact_name_is_the_entry_itself() -> None:
    """A printed name matching an entry name returns that entry, unchanged."""
    assert printed_rule("Stubborn", REPO.rules) is REPO.rules["stubborn"]


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
    assert effect.add == {"armour-piercing": 1}
    # The filed entry is untouched: the placeholder still reads "X".
    filed = REPO.rules["armour-bane"].effects[0]
    assert isinstance(filed, ModifierEffect)
    assert filed.add == {"armour-piercing": "X"}


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
    compiled = compile_rules(["Armour Bane (1)"], index)
    assert compiled.factored == ("Armour Bane (1)",)
    transforms = compiled.modifiers
    profile = AttackProfile.shooting(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    assert resolve_attack(profile, transforms).p_unsaved == Fraction(13, 54)


def test_compile_effectless_rule_stays_unfactored() -> None:
    """A resolved rule with no effects is recognised but not factored.

    Built here rather than taken from data/, where no such entry is allowed to
    exist: a rule the engine cannot apply is filed by not filing it at all.
    """
    effectless = Rule(id="effectless", name="Effectless", paragraphs=["Says nothing."])
    compiled = compile_rules(["Effectless"], {effectless.name: effectless})
    assert compiled.modifiers == ()
    assert compiled.unfactored == ("Effectless",)


def test_compile_rank_quantity_stays_unfactored_in_the_dice_walk() -> None:
    """A rank quantity is not a dice-walk modifier — the walk leaves it unfactored.

    fighting-ranks is read by the fighting-rank query, not the walk; as a
    rule compiled for the walk it produces no modifier and is reported, the
    way a characteristic change is.
    """
    rules = _one_rule(ModifierEffect(add={Quantity.FIGHTING_RANKS: 1}))
    compiled = compile_rules(["Doctored"], rules)
    assert compiled.modifiers == ()
    assert compiled.unfactored == ("Doctored",)


def test_compile_parameter_placeholder_without_value_stays_unfactored() -> None:
    """The X placeholder needs a bracketed number in the printed name."""
    rule = REPO.rules["armour-bane"]
    compiled = compile_rules(["Armour Bane (X)"], REPO.rules)
    assert rule.effects and compiled.modifiers == ()
    assert compiled.unfactored == ("Armour Bane (X)",)


def test_unconditional_armour_piercing_modifier_factors() -> None:
    """An AP change with no trigger lands before every save roll.

    The generic modifier path expresses what the old per-kind compiler
    refused (an AP improvement not gated on a die): hit 3+, wound 4+,
    save 5+ worsened to 6+ on every attack, p = 2/3 * 1/2 * 5/6 = 5/18.
    """
    rules = _one_rule(ModifierEffect(add={Quantity.ARMOUR_PIERCING: 1}))
    compiled = compile_rules(["Doctored"], rules)
    assert compiled.factored == ("Doctored",)
    transforms = compiled.modifiers
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
        when=When(natural=NaturalRoll(face=6, roll=Stage.ROLL_TO_WOUND)), add={Quantity.TO_HIT: 1}
    )
    compiled = compile_rules(["Doctored"], _one_rule(effect))
    assert compiled.modifiers == ()
    assert compiled.unfactored == ("Doctored",)


def test_shoot_unit_factors_armour_bane_from_data() -> None:
    """End to end: the Longbow's Armour Bane (1) changes the math.

    Archers vs spearmen (5+ save): per-shot unsaved moves from 2/9 to
    13/54, the Armour Bane note disappears, and Volley Fire is factored
    into the shot count (stationary, one rank), so it too leaves no note.
    """
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3).wielding("Longbow"),
        _fielded(REPO.units["elven-spearmen"], 10),
        phase_rules=IN_FORCE,
    )
    assert result.p_unsaved == pytest.approx(13 / 54)
    assert not any("Armour Bane" in note for note in result.notes)
    assert not any("Volley Fire" in note for note in result.notes)


def test_weapon_rules_factor_from_the_loadout_alone() -> None:
    """No registry at the action: the weapon's rules ride with the unit.

    Fielding resolved the Longbow's Armour Bane (1), so the volley
    factors it (2/9 -> 13/54 per shot) with no ``rules=`` passed at all;
    Volley Fire is factored into the shot count. Only the shooting phase's
    own chapter rules still come from the registry.
    """
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3).wielding("Longbow"),
        _fielded(REPO.units["elven-spearmen"], 10),
    )
    assert result.p_unsaved == pytest.approx(13 / 54)
    assert not any("Armour Bane" in note for note in result.notes)
    assert not any("Volley Fire" in note for note in result.notes)


def test_long_range_penalty_applies_from_data() -> None:
    """Beyond half range the To Hit target worsens by the printed -1.

    Archers at 20" with 30" longbows: 20 > 15, so hit 4+ instead of 3+;
    with Armour Bane live, p = 1/2 * (2/6 * 2/3 + 1/6 * 5/6) = 13/72.
    """
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3).wielding("Longbow"),
        _fielded(REPO.units["elven-spearmen"], 10),
        phase_rules=IN_FORCE,
        distance=20,
    )
    assert result.p_unsaved == pytest.approx(13 / 72)
    assert not any("core rule" in note for note in result.notes)


def test_condition_false_applies_no_penalty_and_no_note() -> None:
    """Within half range and stationary: no modifier, and no note either.

    A rule whose condition evaluates False is honoured by not applying.
    """
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3).wielding("Longbow"),
        _fielded(REPO.units["elven-spearmen"], 10),
        phase_rules=IN_FORCE,
        distance=10,
    )
    assert result.p_unsaved == pytest.approx(13 / 54)
    assert not any("core rule" in note for note in result.notes)


def test_unknown_distance_leaves_only_the_range_rule_unfactored() -> None:
    """An unknown range leaves only Firing at Long Range unfactored.

    A stationary shooter settles Moving and Shooting — honoured, no
    penalty, no note — so only the range rule is left reported.
    """
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3).wielding("Longbow"),
        _fielded(REPO.units["elven-spearmen"], 10),
        phase_rules=IN_FORCE,
    )
    assert result.p_unsaved == pytest.approx(13 / 54)
    assert any("core rule not factored: Firing at Long Range" in n for n in result.notes)
    assert not any("Moving and Shooting" in n for n in result.notes)


def test_both_penalties_stack() -> None:
    """Moved and at long range: -1 and -1, hit 5+."""
    result = shoot_unit(
        _fielded(REPO.units["elven-archers"], 3, moved=True).wielding("Longbow"),
        _fielded(REPO.units["elven-spearmen"], 10),
        phase_rules=IN_FORCE,
        distance=20,
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
    stay = shoot_unit(
        _fielded(sea_guard, 10).wielding("Warbow"),
        _fielded(spearmen, 10),
        phase_rules=IN_FORCE,
        distance=15,
    )
    move_in = shoot_unit(
        _fielded(sea_guard, 10, moved=True).wielding("Warbow"),
        _fielded(spearmen, 10),
        phase_rules=IN_FORCE,
        distance=12,
    )
    assert stay.hit_target == move_in.hit_target == 4  # the To Hit is a wash
    assert stay.p_unsaved == pytest.approx(move_in.p_unsaved)  # per shot, identical
    assert stay.shots > move_in.shots  # but staying volley fires
    assert stay.expected_casualties > move_in.expected_casualties


def test_wielding_gate_is_tri_state() -> None:
    """The weapon-in-hand gate: matched is True, mismatched False, unknown None.

    A rule gating on the weapon family (Arrows of Isha's "any bow") holds when
    the weapon in hand is a bow, is honoured as a no-op when it is a named other
    weapon, and is unevaluatable when nothing names the weapon's family (a plain
    hand weapon carries no modelled family) — reported, never silently dropped.
    """
    by_family = ModifierEffect(
        when=When.model_validate({"wielding": {"type": "bow"}}),
        add={Quantity.ARMOUR_PIERCING: 1},
    )
    bow = GateContext(wielding=WeaponFacts(type=WeaponType.BOW))
    unarmed = GateContext(wielding=WeaponFacts())  # no family known
    assert _gate_applies(by_family, bow) is True
    assert _gate_applies(by_family, unarmed) is None
    by_name = ModifierEffect(
        when=When.model_validate({"wielding": {"name": "Longbow"}}),
        add={Quantity.ARMOUR_PIERCING: 1},
    )
    armed = GateContext(wielding=WeaponFacts(type=WeaponType.BOW, name="Bow of Avelorn"))
    assert _gate_applies(by_name, armed) is False  # a different named weapon in hand


def test_worn_gate_is_satisfied_by_any_piece_worn() -> None:
    """The armour gate reads a collection: a match anywhere holds, and empty is known.

    The one membership subject — a model wears several pieces at once, so the gate
    describes one piece and any piece worn may satisfy it. A shield among the
    pieces holds however many others there are; a collection without one is
    honoured as a no-op, and so is an *empty* one: wearing nothing is a settled
    fact, not an unanswered one. Only a collection the producer never offered is
    unknown, and it is reported rather than read as "wears nothing".
    """
    effect = ModifierEffect(
        when=When.model_validate({"worn": {"name": "Shield"}}),
        add={Quantity.ARMOUR_VALUE: 1},
    )
    shield_among_others = GateContext(
        worn=(ArmourFacts(name="Light Armour"), ArmourFacts(name="Shield"))
    )
    assert _gate_applies(effect, shield_among_others) is True
    assert _gate_applies(effect, GateContext(worn=(ArmourFacts(name="Heavy Armour"),))) is False
    assert _gate_applies(effect, GateContext(worn=())) is False  # wears nothing, known
    assert _gate_applies(effect, GateContext()) is None  # never offered, unknown


def test_compile_grant_confers_the_named_rule_and_stacks() -> None:
    """Arrows of Isha's grant expands to Armour Bane's own effect, under the bow gate.

    Firing a bow, the rule yields two modifiers: an unconditional Armour Piercing
    improvement (the "-1 characteristic"), and the granted Armour Bane (1) — a +1
    on a natural 6 To Wound, keeping its own inner trigger. It is a separate
    instance from any the weapon prints, so two Armour Banes stack.
    """
    sisters = _fielded(REPO.units["sisters-of-avelorn"], 5).wielding("Bow of Avelorn")
    bow = GateContext(wielding=WeaponFacts(type=WeaponType.BOW))
    index = {rule.name: rule for rule in sisters.loadout.rules}
    compiled = compile_rules(["Arrows of Isha"], index, bow, grants=sisters.loadout.granted_rules)
    assert compiled.factored == ("Arrows of Isha",)
    save_moves = [
        (m.move, m.trigger) for m in compiled.modifiers if m.lands_on is Stage.MAKE_ARMOUR_SAVES
    ]
    assert (1, None) in save_moves  # the unconditional -1 Armour Piercing
    assert any(
        move == 1 and trigger is not None and trigger.face == 6 for move, trigger in save_moves
    )  # the granted Armour Bane, on a natural 6 To Wound


def test_compile_grant_unfactored_when_the_bow_gate_is_unknown() -> None:
    """No known weapon family leaves the whole rule unfactored, reported.

    The grant and the flat Armour Piercing both gate on the weapon being a bow;
    a context that cannot answer that (nothing wielded) factors neither.
    """
    sisters = _fielded(REPO.units["sisters-of-avelorn"], 5).wielding("Bow of Avelorn")
    index = {rule.name: rule for rule in sisters.loadout.rules}
    compiled = compile_rules(
        ["Arrows of Isha"], index, GateContext(), grants=sisters.loadout.granted_rules
    )
    assert compiled.unfactored == ("Arrows of Isha",)
    assert compiled.modifiers == ()


def test_compile_grant_unfactored_when_the_granted_rule_is_unresolvable() -> None:
    """A grant whose named rule has no entry cannot be expanded — unfactored.

    All-or-nothing: the flat clause would compile, but the unresolvable grant
    takes the whole rule down, reported rather than half-applied.
    """
    sisters = _fielded(REPO.units["sisters-of-avelorn"], 5).wielding("Bow of Avelorn")
    bow = GateContext(wielding=WeaponFacts(type=WeaponType.BOW))
    index = {rule.name: rule for rule in sisters.loadout.rules}
    compiled = compile_rules(["Arrows of Isha"], index, bow, grants={})
    assert compiled.unfactored == ("Arrows of Isha",)
    assert compiled.modifiers == ()


def test_scalar_fact_is_tri_state() -> None:
    """A boolean fact walked: unanswerable is unknown (None); else it must match.

    A fact the context cannot answer leaves the rule unevaluatable, never
    silently ignored; a fact the gate does not ask is no constraint.
    """
    effect = ModifierEffect(
        when=When.model_validate({"combat": {"first_round": True}}),
        add={Quantity.COMBAT_RESULT: 1},
    )
    # Combat present but the round unanswered: the property is what is unknown.
    assert _gate_applies(effect, GateContext(combat=CombatFacts())) is None
    assert _gate_applies(effect, GateContext(combat=CombatFacts(first_round=True))) is True
    assert _gate_applies(effect, GateContext(combat=CombatFacts(first_round=False))) is False
    # Combat absent is a known negative, not an unknown: the first-round-of-combat
    # bonus definitely does not apply (there is no combat), honoured as a no-op.
    assert _gate_applies(effect, GateContext()) is False


def test_gate_conjunction_settles_on_a_known_false() -> None:
    """One known-False fact settles the gate, even beside an unknown one.

    A gate on movement.moved and shooting.at_long_range against a stationary
    shooter at an unknown range definitely does not apply — a no-op, not
    "cannot be evaluated"; a matching known fact beside an unknown stays None.
    """
    effect = ModifierEffect(
        when=When.model_validate(
            {"movement": {"moved": True}, "shooting": {"at_long_range": True}}
        ),
        add={Quantity.TO_HIT: -1},
    )
    assert _gate_applies(effect, GateContext(movement=MovementFacts(moved=False))) is False
    assert _gate_applies(effect, GateContext(movement=MovementFacts(moved=True))) is None
    assert (
        _gate_applies(
            effect,
            GateContext(
                movement=MovementFacts(moved=True), shooting=ShootingFacts(at_long_range=True)
            ),
        )
        is True
    )


def test_every_roll_quantity_declares_its_roll() -> None:
    """Each roll-seam quantity maps onto a roll the attack profile carries.

    Drift guard for the table's exhaustiveness: a quantity whose seam is the
    dice walk must declare which roll it changes, and the profile must carry
    a target for that roll's stage. The seam vocabulary is introspected, so
    new members are covered automatically.
    """
    from avelorn.tow.engine.rules import _ROLLS
    from avelorn.tow.schema.rule import Quantity, Seam

    profile = AttackProfile.shooting(hit_target=4, wound_target=4, save_target=4, ward_target=4)
    roll_quantities = [q for q in Quantity if q.seam is Seam.ROLL]
    for quantity in roll_quantities:
        assert quantity in _ROLLS, quantity
        profile.target(_ROLLS[quantity].stage)  # KeyError if the stage rolls no target


def test_armour_bane_two_leaves_no_save_at_all() -> None:
    """Armour Bane (2) pushes a 5+ save past 6+: the save is not taken.

    What the moved target means is the roll's own knowledge — a save
    worse than 6+ cannot be attempted; the modifier only moves the
    number. Hit 3+, wound 4+, save 5+:
    p = 2/3 * (2/6 * 4/6 + 1/6 * 1) = 7/27.
    """
    bane = printed_rule("Armour Bane (2)", REPO.rules)
    assert bane is not None
    compiled = compile_rules(["Armour Bane (2)"], {bane.name: bane})
    assert compiled.factored == ("Armour Bane (2)",)
    transforms = compiled.modifiers
    profile = AttackProfile.shooting(
        hit_target=3, wound_target=4, save_target=5, ward_target=RollState.IMPOSSIBLE
    )
    assert resolve_attack(profile, transforms).p_unsaved == Fraction(7, 27)


# --- effective_characteristic: the characteristic-read query ---


def _initiative_rule(
    amount: int | Literal["X"] = 1,
    maximum: int | None = 10,
    when: dict[str, object] | None = None,
    characteristic: Characteristic = Characteristic.INITIATIVE,
) -> Rule:
    payload: dict[str, object] = {"add": {characteristic: amount}, "maximum": maximum}
    if when is not None:
        payload["when"] = when
    effect = ModifierEffect.model_validate(payload)
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
    rule = _initiative_rule(when={"combat": {"first_round": True}})
    # Combat present, its round unanswered: the gate cannot be evaluated.
    result = effective_characteristic(
        4, Characteristic.INITIATIVE, [rule], GateContext(combat=CombatFacts())
    )
    assert result.value == 4
    assert result.factored == ()
    assert result.unfactored == ("Doctored (X)",)


def test_effective_characteristic_false_condition_is_honoured() -> None:
    """A condition answered False applies nothing — factored, not reported."""
    rule = _initiative_rule(when={"combat": {"first_round": True}})
    result = effective_characteristic(
        4, Characteristic.INITIATIVE, [rule], GateContext(combat=CombatFacts(first_round=False))
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


# --- set: the replace operation, before its Strike First/Last data lands ---


def _set_initiative(value: int, name: str = "Doctored Set") -> Rule:
    # A rule that sets Initiative outright — the Strike First/Last shape, ahead of
    # its real data: `set: {I: value}`, no add.
    effect = ModifierEffect(set={Characteristic.INITIATIVE: value})
    return Rule(id="doctored-set", name=name, paragraphs=["…"], effects=[effect])


def test_effective_characteristic_set_replaces_the_base() -> None:
    """A set operation replaces the base value outright, and is factored."""
    result = effective_characteristic(4, Characteristic.INITIATIVE, [_set_initiative(10)])
    assert result.value == 10
    assert result.factored == ("Doctored Set",)
    assert result.unfactored == ()


def test_effective_characteristic_set_lands_before_add() -> None:
    """A set replaces the base before additive modifiers stack on top.

    Strike Last's shape (set to 1) beside a separate +1 (a charge, say): the
    set lands first, so the base 4 is replaced by 1 and the add lifts it to 2 —
    not 5. Order in the list must not matter, so the add rule leads here.
    """
    result = effective_characteristic(
        4,
        Characteristic.INITIATIVE,
        [_initiative_rule(amount=1, maximum=None), _set_initiative(1)],
    )
    assert result.value == 2


def test_effective_characteristic_set_then_add_still_caps() -> None:
    """Set to 10, then +1, capped by the add's printed maximum (Strike First on a charge)."""
    result = effective_characteristic(
        4,
        Characteristic.INITIATIVE,
        [_set_initiative(10), _initiative_rule(amount=1, maximum=10)],
    )
    assert result.value == 10


def test_effective_characteristic_conflicting_sets_cancel() -> None:
    """Two rules setting the same characteristic to different values cancel.

    Strike First (to 10) against Strike Last (to 1): the base stands, and both
    rules are honoured — factored, just to no effect. This is the rule-agnostic
    model of the printed "the two rules cancel one another out" clause.
    """
    result = effective_characteristic(
        4,
        Characteristic.INITIATIVE,
        [_set_initiative(10, "Set High"), _set_initiative(1, "Set Low")],
    )
    assert result.value == 4
    assert set(result.factored) == {"Set High", "Set Low"}
    assert result.unfactored == ()


def test_effective_characteristic_agreeing_sets_apply_once() -> None:
    """Only disagreeing sets cancel; two rules setting the same value still apply."""
    result = effective_characteristic(
        4, Characteristic.INITIATIVE, [_set_initiative(10, "A"), _set_initiative(10, "B")]
    )
    assert result.value == 10
    assert set(result.factored) == {"A", "B"}


def test_set_is_unfactored_at_the_walk() -> None:
    """A set reaching the dice walk belongs to another seam — unfactored, not applied.

    The walk moves a roll's target; a set replaces a base the effective-value
    query reads. A characteristic set as a weapon rule compiles to no modifier
    and is reported, the way a characteristic add is. (A set on a roll quantity
    cannot reach here — the schema rejects it at load.)
    """
    effect = ModifierEffect(set={Characteristic.INITIATIVE: 10})
    compiled = compile_rules(["Doctored"], _one_rule(effect))
    assert compiled.modifiers == ()
    assert compiled.unfactored == ("Doctored",)


def _press_of_battle() -> Rule:
    # A rank modifier in the Press of Battle shape: +1 fighting rank, off on a charge.
    effect = ModifierEffect(
        when=When.model_validate({"movement": {"charge": False}}), add={Quantity.FIGHTING_RANKS: 1}
    )
    return Rule(id="doctored", name="Doctored", paragraphs=["…"], effects=[effect])


def test_effective_fighting_ranks_folds_a_rank_modifier() -> None:
    """A rank modifier deepens the base of one, gated on the charge event.

    Not charging: the +1 lands (two ranks), factored. Charging: honoured by
    not applying (one rank), still factored. The charge is always known (a
    model's movement is settled), so there is no unknown-charge case — the
    tri-state unknown lives on the flat conditions, not on the event.
    """
    stationary = effective_fighting_ranks(1, [_press_of_battle()], GateContext())
    assert stationary.value == 2
    assert stationary.factored == ("Doctored",)

    charging = GateContext(movement=MovementFacts(charge=ChargeEvent(distance=6)))
    charged = effective_fighting_ranks(1, [_press_of_battle()], charging)
    assert charged.value == 1
    assert charged.factored == ("Doctored",)


def test_effective_supporting_ranks_folds_over_a_base_of_none() -> None:
    """The supporting-ranks twin: base zero, a +1 rank rule gated on the charge.

    Stationary: the +1 lands (one supporting rank), factored. Charging:
    honoured by not applying (none), still factored.
    """
    effect = ModifierEffect(
        when=When.model_validate({"movement": {"charge": False}}),
        add={Quantity.SUPPORTING_RANKS: 1},
    )
    rule = Rule(id="doctored", name="Doctored", paragraphs=["…"], effects=[effect])

    stationary = effective_supporting_ranks(0, [rule], GateContext())
    assert stationary.value == 1
    assert stationary.factored == ("Doctored",)

    charged = effective_supporting_ranks(
        0, [rule], GateContext(movement=MovementFacts(charge=ChargeEvent(distance=6)))
    )
    assert charged.value == 0
    assert charged.factored == ("Doctored",)


def test_gate_and_context_mirror_each_other() -> None:
    """Every gate property the schema declares has a matching context fact.

    Drift guard: the evaluator reads a gate's property off the same-named field
    of the context (a subject's facts, or the charge event), so a property added
    to a gate model without the matching context field would evaluate against
    nothing. The When subjects, their gates, and the mirroring facts dataclasses
    must stay in step — as must ChargeGate and ChargeEvent, and a membership
    gate and the member behind it (ArmourGate against one piece worn).
    """
    from dataclasses import fields

    from avelorn.tow.schema.rule import (
        ArmourGate,
        AttackGate,
        CombatGate,
        MovementGate,
        ShootingGate,
        WeaponGate,
    )

    pairs = [
        (CombatGate, CombatFacts),
        (MovementGate, MovementFacts),
        (ShootingGate, ShootingFacts),
        (WeaponGate, WeaponFacts),
        (ArmourGate, ArmourFacts),
        (AttackGate, AttackFacts),
        (ChargeGate, ChargeEvent),
    ]
    for gate, facts in pairs:
        gate_properties = set(gate.model_fields)
        context_fields = {f.name for f in fields(facts)}
        assert gate_properties <= context_fields, gate.__name__


def test_a_gate_that_cannot_hook_the_context_raises() -> None:
    """A gate node with no matching context fact is a loud drift error.

    The generic walk requires every constrained gate field to name a context
    fact; a mismatch (the gate and context shapes drifted) raises rather than
    silently passing — the snag the drift guard above is meant to prevent.
    """
    from avelorn.tow.engine.rules import _walk
    from avelorn.tow.schema.rule import MovementGate

    with pytest.raises(TypeError, match="no matching fact"):
        _walk(MovementGate(moved=True), CombatFacts())


def test_effective_combat_result_bonus_sums_signed_points_under_the_conditions() -> None:
    """The combat-result fold: +1 when the condition holds, 0 when it does not.

    Outnumbering: the +1 lands, factored. Even: honoured by not applying,
    still factored. Unknown: unfactored, its point left out of the total.
    """
    effect = ModifierEffect(
        when=When.model_validate({"combat": {"outnumbers": True}}), add={Quantity.COMBAT_RESULT: 1}
    )
    rule = Rule(id="massed", name="Massed Infantry", paragraphs=["…"], effects=[effect])

    outnumbering = effective_combat_result_bonus(
        [rule], GateContext(combat=CombatFacts(outnumbers=True))
    )
    assert outnumbering.value == 1
    assert outnumbering.factored == ("Massed Infantry",)

    even = effective_combat_result_bonus([rule], GateContext(combat=CombatFacts(outnumbers=False)))
    assert even.value == 0
    assert even.factored == ("Massed Infantry",)

    unknown = effective_combat_result_bonus([rule], GateContext(combat=CombatFacts()))
    assert unknown.value == 0
    assert unknown.unfactored == ("Massed Infantry",)


def test_effective_armour_value_betters_the_save_with_the_gear_its_gate_names() -> None:
    """Parry lowers the armour value by one, gated on the equipment in use.

    The real rule from the data, gated on the weapon in hand and on a shield
    among the armour worn. Both in use: the +1 lands (a save one better),
    floored at the printed best of 3+. Another piece worn, or nothing worn at
    all: honoured, no change — the armour worn is settled either way. Nothing in
    hand, or the armour never offered: unfactored, the fact unanswered.
    """
    rule = REPO.rules["parry"]
    hand_weapon = WeaponFacts(name="Hand Weapon")
    shield = (ArmourFacts(name="Shield"),)

    def save(
        base: int, wielding: WeaponFacts, worn: tuple[ArmourFacts, ...] | None
    ) -> EffectiveValue:
        conditions = GateContext(combat=CombatFacts(), wielding=wielding, worn=worn)
        return effective_armour_value(base, [rule], conditions)

    equipped = save(5, hand_weapon, shield)
    assert equipped.value == 4  # a 5+ save bettered to 4+
    assert equipped.factored == ("Parry",)

    capped = save(3, hand_weapon, shield)
    assert capped.value == 3  # cannot improve past the best save of 3+

    other_armour = save(5, hand_weapon, (ArmourFacts(name="Light Armour"),))
    assert other_armour.value == 5  # honoured: no shield among the pieces worn
    assert other_armour.factored == ("Parry",)

    unarmoured = save(5, hand_weapon, ())
    assert unarmoured.value == 5  # honoured: wearing nothing is known, not unknown
    assert unarmoured.factored == ("Parry",)

    unarmed = save(5, WeaponFacts(), shield)
    assert unarmed.value == 5
    assert unarmed.unfactored == ("Parry",)  # the weapon in hand is unknown

    no_loadout = save(5, hand_weapon, None)
    assert no_loadout.value == 5
    assert no_loadout.unfactored == ("Parry",)  # the armour worn was never offered


def test_effective_armour_value_speaks_for_an_unarmoured_defenders_rules() -> None:
    """No printed value to improve, and the rules still get their disposition read.

    A defender wearing nothing passes a None base. Parry names a shield, which a
    model wearing nothing cannot have, so it is honoured and factored — the fold
    has spoken for it, and no caller need report it as though no seam looked. A
    rule that *would* improve the value is reported instead: the engine will not
    invent a save out of a value the defender does not have.
    """
    bare = GateContext(combat=CombatFacts(), wielding=WeaponFacts(name="Hand Weapon"), worn=())

    honoured = effective_armour_value(None, [REPO.rules["parry"]], bare)
    assert honoured.value == 0  # the caller's "no save"
    assert honoured.factored == ("Parry",)

    ungated = _one_rule(ModifierEffect(add={Quantity.ARMOUR_VALUE: 1}))["Doctored"]
    would_apply = effective_armour_value(None, [ungated], bare)
    assert would_apply.value == 0
    assert would_apply.unfactored == ("Doctored",)


def test_lion_cloak_betters_the_save_only_against_non_magical_shooting() -> None:
    """Lion Cloak reads the incoming attack, not the model's state.

    The real rule from the data: +1 armour value (a save one better), floored
    at the printed best of 2+, against a non-magical shooting attack. Against a
    magical shot, or a close-combat attack, it is honoured as a no-op — the
    gate reads the attack's kind and whether it is magical, so a magical bow
    (the Bow of Avelorn) turns the cloak's protection off.
    """
    rule = REPO.rules["lion-cloak"]

    def save(target_of: AttackFacts | None) -> EffectiveValue:
        return effective_armour_value(4, [rule], GateContext(target_of=target_of))

    plain_shot = save(AttackFacts(kind=AttackKind.SHOOTING, magical=False))
    assert plain_shot.value == 3  # a 4+ save bettered to 3+
    assert plain_shot.factored == ("Lion Cloak",)

    capped = effective_armour_value(
        2,
        [rule],
        GateContext(target_of=AttackFacts(kind=AttackKind.SHOOTING, magical=False)),
    )
    assert capped.value == 2  # cannot improve past the best save of 2+

    magical_shot = save(AttackFacts(kind=AttackKind.SHOOTING, magical=True))
    assert magical_shot.value == 4  # honoured: a magical shot pierces the cloak
    assert magical_shot.factored == ("Lion Cloak",)

    melee = save(AttackFacts(kind=AttackKind.CLOSE_COMBAT, magical=False))
    assert melee.value == 4  # honoured: not a shooting attack
    assert melee.factored == ("Lion Cloak",)


def test_effective_rerolls_grants_ithilmar_weapons_with_the_gear_its_gate_names() -> None:
    """Ithilmar Weapons re-rolls To Hit natural 1s, gated on gear and engagement.

    Engaged and fighting with a hand weapon: the grant is a To Hit re-roll of
    natural 1s. Wielding anything else: honoured, no grant. The weapon in hand
    unknown (nothing armed): unfactored. Combat absent: honoured — no combat,
    no re-roll.
    """
    rule = REPO.rules["ithilmar-weapons"]

    def engaged(wielding: WeaponFacts) -> GateContext:
        return GateContext(combat=CombatFacts(), wielding=wielding)

    armed = effective_rerolls([rule], engaged(WeaponFacts(name="Hand Weapon")))
    assert armed.factored == ("Ithilmar Weapons",)
    assert [(r.stage, r.on_natural) for r in armed.rerolls] == [(Stage.ROLL_TO_HIT, 1)]

    great_blade = effective_rerolls([rule], engaged(WeaponFacts(name="Chracian Great Blade")))
    assert great_blade.factored == ("Ithilmar Weapons",)  # honoured: not a hand weapon
    assert great_blade.rerolls == ()

    unarmed = effective_rerolls([rule], engaged(WeaponFacts()))
    assert unarmed.unfactored == ("Ithilmar Weapons",)  # the weapon in hand is unknown
    assert unarmed.rerolls == ()

    hand_weapon = GateContext(wielding=WeaponFacts(name="Hand Weapon"))  # but no combat
    not_in_combat = effective_rerolls([rule], hand_weapon)
    assert not_in_combat.factored == ("Ithilmar Weapons",)  # honoured: no combat
    assert not_in_combat.rerolls == ()


def test_effective_rerolls_route_a_bearers_save_re_roll_to_the_target_seat() -> None:
    """Gromril Armour re-rolls the bearer's own save: only the attacks it suffers.

    Make Armour Saves is the target's die and the sentence speaks of the
    bearer, so the grant fires at the target seat and is inapplicable at the
    attacker seat — a Gromril unit strikes without touching the enemy's saves
    (the case that used to compile off the attacker).
    """
    rule = REPO.rules["gromril-armour"]

    defending = effective_rerolls([rule], seat=Side.TARGET)
    assert defending.factored == ("Gromril Armour",)
    assert [(r.stage, r.on_natural, r.of) for r in defending.rerolls] == [
        (Stage.MAKE_ARMOUR_SAVES, 1, RollResult.FAILED)
    ]

    attacking = effective_rerolls([rule], seat=Side.ATTACKER)
    assert attacking.inapplicable == ("Gromril Armour",)  # the other seat's die
    assert attacking.factored == ()  # nothing here consumed it
    assert attacking.rerolls == ()


def test_effective_rerolls_route_an_enemy_save_re_roll_to_the_attacker_seat() -> None:
    """Daith's Reaper re-rolls the enemy's successful saves: only the attacks it makes.

    The printed subject is the enemy, so the target-rolled die flips to the
    attacker seat; while the bearer defends, the grant is inapplicable — its
    own saves stand, and nothing in that walk is the rule's business.
    """
    rule = REPO.rules["daiths-reaper"]

    attacking = effective_rerolls([rule], seat=Side.ATTACKER)
    assert attacking.factored == ("Daith's Reaper",)
    assert [(r.stage, r.on_natural, r.of) for r in attacking.rerolls] == [
        (Stage.MAKE_ARMOUR_SAVES, None, RollResult.SUCCESSFUL)
    ]

    defending = effective_rerolls([rule], seat=Side.TARGET)
    assert defending.inapplicable == ("Daith's Reaper",)
    assert defending.factored == ()
    assert defending.rerolls == ()


def test_enemy_fire_compiles_off_the_target_against_the_shooters_roll() -> None:
    """Enemy Fire (Skirmishers): the defender's rule, the attacker's die.

    Compiled off the skirmishers — the target of a shooting attack — the
    enemy-subject -1 To Hit raises the walk's Roll to Hit target by one.
    Compiled off the same unit as an attacker, the malus names the seat this
    compile is not: inapplicable, neither factored (nothing consumed it) nor
    unfactored (the compile at the other seat has it).
    """
    rule = REPO.rules["enemy-fire-skirmishers"]
    index = {rule.name: rule}
    shot_at = GateContext(target_of=AttackFacts(kind=AttackKind.SHOOTING))

    compiled = compile_rules([rule.name], index, shot_at, seat=Side.TARGET)
    assert compiled.factored == (rule.name,)
    assert [(m.lands_on, m.move, m.trigger) for m in compiled.modifiers] == [
        (Stage.ROLL_TO_HIT, 1, None)
    ]

    as_attacker = compile_rules([rule.name], index, GateContext(), seat=Side.ATTACKER)
    assert as_attacker.inapplicable == (rule.name,)
    assert as_attacker.factored == () and as_attacker.unfactored == ()
    assert as_attacker.modifiers == ()


def test_compile_seat_mismatch_is_settled_before_the_gate() -> None:
    """The other seat's business is decided from the effect, never from the facts.

    Enemy Fire's own gate ("is this unit the target of a shooting attack?") is
    answerable one way at the attacker seat and unanswerable the other, yet the
    rule is inapplicable there either way: the seat is read off the quantity,
    ahead of the gate, so a one-sided caller's report never turns on gate luck.
    """
    rule = REPO.rules["enemy-fire-skirmishers"]
    index = {rule.name: rule}
    contexts = {
        "unknown": GateContext(),
        "not a target": GateContext(target_of=None),
        "a target": GateContext(target_of=AttackFacts(kind=AttackKind.SHOOTING)),
    }
    for described, context in contexts.items():
        compiled = compile_rules([rule.name], index, context, seat=Side.ATTACKER)
        assert compiled.inapplicable == (rule.name,), described


def test_compile_another_seams_quantity_is_unfactored_whatever_the_gate_answers() -> None:
    """A characteristic modifier is no seat's business — reported, gate or no gate.

    Elven Reflexes' +1 Initiative is the characteristic query's, and *that*
    fold is the one with a say on it. Neither seat of a dice walk can consume
    it, so the walk reports it whether its combat gate answers True, False (a
    volley: no combat) or unknown — never quietly factored because the facts
    happened to settle the gate False.
    """
    rule = REPO.rules["elven-reflexes"]
    index = {rule.name: rule}
    contexts = {
        "first round": GateContext(combat=CombatFacts(first_round=True)),
        "a later round": GateContext(combat=CombatFacts(first_round=False)),
        "round unknown": GateContext(combat=CombatFacts()),
        "no combat at all": GateContext(),  # the volley context: combat absent, gate False
    }
    for described, context in contexts.items():
        for seat in Side:
            compiled = compile_rules([rule.name], index, context, seat=seat)
            assert compiled.unfactored == (rule.name,), f"{described}, {seat}"
            assert compiled.modifiers == ()


def test_effective_ward_target_grants_the_best_ward_and_never_stacks() -> None:
    """Two ward grants do not combine; the best (lowest) Warding value applies.

    A different fold from the armour seam's additive one: 5+ beside 6+ is a
    5+ ward, never a 4+ (the-shooting-phase/ward-saves; #131).
    """
    five = Rule(
        id="five",
        name="Five",
        paragraphs=["…"],
        effects=[ModifierEffect(set={Quantity.WARD_SAVE: 5})],
    )
    six = Rule(
        id="six",
        name="Six",
        paragraphs=["…"],
        effects=[ModifierEffect(set={Quantity.WARD_SAVE: 6})],
    )
    ward = effective_ward_target([six, five])
    assert ward.target == 5
    assert set(ward.factored) == {"Five", "Six"}
    assert ward.unfactored == ()


def test_effective_ward_target_is_none_when_nothing_grants_one() -> None:
    """A unit whose rules grant no ward has no ward, not a ward of zero."""
    ward = effective_ward_target([REPO.rules["stubborn"]])
    assert ward.target is None
    assert ward.factored == ()
    assert ward.unfactored == ()


def test_runes_of_protection_ward_reads_the_incoming_attacks_magic() -> None:
    """The real entry: a 6+ ward against a non-magical attack, none against a magical one.

    A magical volley (the Bow of Avelorn) answers the gate False: honoured,
    factored, and no ward granted. An attack whose magic is unknown leaves the
    rule unfactored, reported rather than guessed.
    """
    rule = REPO.rules["runes-of-protection"]

    mundane = GateContext(target_of=AttackFacts(kind=AttackKind.SHOOTING, magical=False))
    warded = effective_ward_target([rule], mundane)
    assert warded.target == 6
    assert warded.factored == ("Runes of Protection",)

    magical = GateContext(target_of=AttackFacts(kind=AttackKind.SHOOTING, magical=True))
    unwarded = effective_ward_target([rule], magical)
    assert unwarded.target is None
    assert unwarded.factored == ("Runes of Protection",)

    unknown = effective_ward_target([rule], GateContext(target_of=AttackFacts()))
    assert unknown.target is None
    assert unknown.unfactored == ("Runes of Protection",)


def test_a_worn_gated_ward_reads_the_equipment_like_any_other_gate() -> None:
    """A ward granted by a piece of equipment gates on the armour worn.

    The equipment path of #131: a talisman-shaped rule whose gate names a worn
    piece grants the ward only while that piece is worn -- the same worn
    subject Parry reads, so items file as rules and need no armour-schema word.
    """
    talisman = Rule(
        id="talisman",
        name="Talisman",
        paragraphs=["…"],
        effects=[
            ModifierEffect(
                set={Quantity.WARD_SAVE: 6},
                when=When(worn=ArmourGate(name="Shield")),
            )
        ],
    )
    shielded = GateContext(worn=(ArmourFacts(name="Shield"),))
    assert effective_ward_target([talisman], shielded).target == 6

    bare = GateContext(worn=())
    honoured = effective_ward_target([talisman], bare)
    assert honoured.target is None
    assert honoured.factored == ("Talisman",)


def test_attack_marks_read_the_profile_in_use_and_the_unit_rules_alike() -> None:
    """The printed sentence confers either way: a marked weapon, or a marked model.

    Real entries: the Bow of Avelorn's profile prints Magical Attacks, and the
    Drakegun's prints Flaming Attacks. A unit whose own special rule is the
    mark carries it onto any weapon it swings. The consumed names come back
    per source, so each claims its own namespace's note.
    """
    magical = REPO.rules["magical-attacks"]
    weapon_rules = {"Magical Attacks": magical}

    by_weapon = attack_marks(["Magical Attacks"], weapon_rules, [])
    assert by_weapon.magical and not by_weapon.flaming
    assert by_weapon.weapon_factored == ("Magical Attacks",)
    assert by_weapon.unit_factored == ()

    by_unit = attack_marks([], {}, [REPO.rules["flaming-attacks"]])
    assert by_unit.flaming and not by_unit.magical
    assert by_unit.unit_factored == ("Flaming Attacks",)

    unmarked = attack_marks([], {}, [REPO.rules["stubborn"]])
    assert not unmarked.magical and not unmarked.flaming


def test_a_gated_attack_mark_is_left_unconsumed() -> None:
    """A mark carrying a `when` cannot be honoured while the facts are being built."""
    gated = Rule(
        id="doctored",
        name="Doctored",
        paragraphs=["…"],
        effects=[AttackMarkEffect(attack=AttackMarks(magical=True), when=When(combat=True))],
    )
    marks = attack_marks([], {}, [gated])
    assert not marks.magical
    assert marks.unit_factored == ()
