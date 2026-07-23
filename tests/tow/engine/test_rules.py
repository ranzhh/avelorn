"""Rule compilation tests: printed names to transforms, from real data."""

from fractions import Fraction
from typing import Literal

import pytest

from avelorn.tow.contingent import Contingent, Movement
from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.attack import AttackProfile, RollState, resolve_attack
from avelorn.tow.engine.rules import (
    AttackFacts,
    ChargeEvent,
    CombatFacts,
    EffectiveValue,
    GateContext,
    MovementFacts,
    ShootingFacts,
    _gate_applies,
    compile_rules,
    effective_armour_value,
    effective_characteristic,
    effective_combat_result_bonus,
    effective_fighting_ranks,
    effective_supporting_ranks,
    printed_rule,
)
from avelorn.tow.phases.shooting import shoot_unit
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.rule import (
    AttackKind,
    ChargeGate,
    EquipmentUse,
    ModifierEffect,
    NaturalRoll,
    Quantity,
    Rule,
    RuleEffect,
    When,
)
from avelorn.tow.schema.stage import Stage
from avelorn.tow.schema.unit import Characteristic, Unit

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


def test_compile_rank_quantity_stays_unfactored_in_the_dice_walk() -> None:
    """A rank quantity is not a dice-walk modifier — the walk leaves it unfactored.

    fighting-ranks is read by the fighting-rank query, not the walk; as a
    rule compiled for the walk it produces no modifier and is reported, the
    way a characteristic change is.
    """
    rules = _one_rule(ModifierEffect(add={Quantity.FIGHTING_RANKS: 1}))
    transforms, unfactored = compile_rules(["Doctored"], rules)
    assert transforms == []
    assert unfactored == ["Doctored"]


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
    rules = _one_rule(ModifierEffect(add={Quantity.ARMOUR_PIERCING: 1}))
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
        when=When(natural=NaturalRoll(face=6, roll=Stage.ROLL_TO_WOUND)), add={Quantity.TO_HIT: 1}
    )
    transforms, unfactored = compile_rules(["Doctored"], _one_rule(effect))
    assert transforms == []
    assert unfactored == ["Doctored"]


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
    modifiers, unfactored = compile_rules(["Doctored"], _one_rule(effect))
    assert modifiers == []
    assert unfactored == ["Doctored"]


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
    must stay in step — as must ChargeGate and ChargeEvent.
    """
    from dataclasses import fields

    from avelorn.tow.schema.rule import (
        AttackGate,
        CombatGate,
        MovementGate,
        ShootingGate,
    )

    pairs = [
        (CombatGate, CombatFacts),
        (MovementGate, MovementFacts),
        (ShootingGate, ShootingFacts),
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


def test_effective_armour_value_betters_the_save_with_the_gear_it_requires() -> None:
    """Parry lowers the armour value by one, gated on the equipment it requires.

    Hand weapon and shield in use: the +1 lands (a save one better), floored
    at the printed best of 3+. Without the shield: honoured, no change. With
    the weapon in hand unknown (nothing armed): unfactored.
    """
    effect = ModifierEffect(
        requires={EquipmentUse.WIELDING: "Hand Weapon", EquipmentUse.WORN: "Shield"},
        add={Quantity.ARMOUR_VALUE: 1},
        maximum=3,
    )
    rule = Rule(id="parry", name="Parry", paragraphs=["…"], effects=[effect])

    equipped = effective_armour_value(5, [rule], wielding="Hand Weapon", worn=["Shield"])
    assert equipped.value == 4  # a 5+ save bettered to 4+
    assert equipped.factored == ("Parry",)

    capped = effective_armour_value(3, [rule], wielding="Hand Weapon", worn=["Shield"])
    assert capped.value == 3  # cannot improve past the best save of 3+

    no_shield = effective_armour_value(5, [rule], wielding="Hand Weapon", worn=["Light Armour"])
    assert no_shield.value == 5  # honoured: the required gear is not in use
    assert no_shield.factored == ("Parry",)

    unarmed = effective_armour_value(5, [rule], wielding=None, worn=["Shield"])
    assert unarmed.value == 5
    assert unarmed.unfactored == ("Parry",)  # the weapon in hand is unknown


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
        return effective_armour_value(
            4, [rule], GateContext(target_of=target_of), wielding=None, worn=[]
        )

    plain_shot = save(AttackFacts(kind=AttackKind.SHOOTING, magical=False))
    assert plain_shot.value == 3  # a 4+ save bettered to 3+
    assert plain_shot.factored == ("Lion Cloak",)

    capped = effective_armour_value(
        2,
        [rule],
        GateContext(target_of=AttackFacts(kind=AttackKind.SHOOTING, magical=False)),
        wielding=None,
        worn=[],
    )
    assert capped.value == 2  # cannot improve past the best save of 2+

    magical_shot = save(AttackFacts(kind=AttackKind.SHOOTING, magical=True))
    assert magical_shot.value == 4  # honoured: a magical shot pierces the cloak
    assert magical_shot.factored == ("Lion Cloak",)

    melee = save(AttackFacts(kind=AttackKind.CLOSE_COMBAT, magical=False))
    assert melee.value == 4  # honoured: not a shooting attack
    assert melee.factored == ("Lion Cloak",)
