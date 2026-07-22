"""Close-combat strike tests, golden values hand-computed from the charts."""

import pytest

from avelorn.core.dice import binomial_distribution, expected_value
from avelorn.tow.contingent import Charge, ChargeArc, Contingent, Loadout
from avelorn.tow.data import TOWRepository
from avelorn.tow.phases.combat import (
    CombatPhase,
    FightResult,
    combat_result,
    effective_initiative,
    effective_weapon_skill,
    fight,
    strike,
    strike_unit,
)
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.rule import Condition, ModifierEffect, Quantity, Rule
from avelorn.tow.schema.unit import Characteristic, Unit
from avelorn.tow.schema.weapon import Weapon

REPO = TOWRepository()

# The shooting chapter's rules in force, built directly: these tests
# exercise the combat layer, which must not depend on game assembly.
IN_FORCE = {r.name: r for r in REPO.rules.values() if r.category == Phase.SHOOTING and r.effects}

# The Combat phase with no chapter rules in force, for fighting an engagement.
COMBAT = CombatPhase(in_play={})


def _fielded(unit: Unit, models: int, *, frontage: int | None = None) -> Contingent:
    # Field at the printed, optionless loadout, with the real registries.
    return Contingent.field(unit, models, data=REPO, frontage=frontage)


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
    spearmen = REPO.units["elven-spearmen"]
    result = strike_unit(
        _fielded(spearmen, 5).wielding("Thrusting Spear"),
        _fielded(spearmen, 10),
    )
    assert result.attacks == 5  # a single fighting rank of five, A1
    assert result.hit_target == 4
    assert result.wound_target == 4
    assert result.save_target == 5
    assert result.p_unsaved == pytest.approx(1 / 6)
    assert not any("Fight In Extra Rank" in note for note in result.notes)  # now factored
    assert any("Valour of Ages" in note for note in result.notes)  # unit special rule
    assert any("thrusting spear" in note.lower() for note in result.notes)  # weapon notes


def test_strike_unit_parry_betters_the_targets_save_with_hand_weapon_and_shield() -> None:
    """A target using a hand weapon and shield parries: its save is one better.

    Elven Spearmen carry light armour and a shield (a 5+ save). Fielded
    wielding a Hand Weapon, Parry improves it to 4+; wielding a Thrusting
    Spear instead, the hand-weapon requirement is unmet and the save stays 5+.
    """
    spearmen = REPO.units["elven-spearmen"]
    attacker = _fielded(spearmen, 5).wielding("Hand Weapon")

    parrying = strike_unit(attacker, _fielded(spearmen, 10).wielding("Hand Weapon"))
    assert parrying.save_target == 4  # 5+ bettered to 4+ by Parry

    spear = strike_unit(attacker, _fielded(spearmen, 10).wielding("Thrusting Spear"))
    assert spear.save_target == 5  # not a hand weapon: Parry honoured, no change


def test_fight_parry_is_claimed_when_both_sides_use_hand_weapon_and_shield() -> None:
    """Both sides' saves are resolved in a fight, so both claim Parry from the notes.

    Each Elven Spearmen body wields a Hand Weapon over its shield, so Parry is
    evaluated for each as the other's target and leaves no "not factored" note.
    """
    spearmen = REPO.units["elven-spearmen"]
    result = fight(
        _fielded(spearmen, 5).wielding("Hand Weapon"),
        _fielded(spearmen, 5).wielding("Hand Weapon"),
    )
    assert not any("Parry" in note for note in result.notes)


def test_strike_unit_notes_the_troop_types_conferred_rules() -> None:
    """Rules a troop type confers surface as unfactored, owned by the type.

    Elven Spearmen are Regular Infantry, which confers Press of Battle,
    Massed Infantry and Parry — none printed on the datasheet. Each is
    reported not factored and attributed to the troop type, not the unit.
    """
    spearmen = REPO.units["elven-spearmen"]
    result = strike_unit(_fielded(spearmen, 5).wielding("Thrusting Spear"), _fielded(spearmen, 10))
    for rule in ("Press of Battle", "Massed Infantry", "Parry"):
        assert any(f"{rule} (Regular Infantry)" in note for note in result.notes)


def test_strike_unit_attacks_scale_with_the_attacks_characteristic() -> None:
    """The fighting rank makes its full Attacks: A2 over a rank of 5 is 10 attacks."""
    spearmen = REPO.units["elven-spearmen"]
    two_attacks = spearmen.model_copy(deep=True)
    two_attacks.profiles[0].characteristics[Characteristic.ATTACKS] = 2
    result = strike_unit(
        _fielded(two_attacks, 5).wielding("Thrusting Spear"),
        _fielded(spearmen, 10),
    )
    assert result.attacks == 10


def test_strike_unit_fights_two_full_ranks_plus_a_supporting_rank() -> None:
    """A stationary spear block fights three ranks: two full, one supporting.

    Elven Spearmen (Regular Infantry, A1) with thrusting spears, stationary:
    Press of Battle makes the front two ranks fight at full Attacks and Fight
    in Extra Rank lets the third rank support at one attack each — fifteen
    models throw 10 + 5 = 15. A fourth rank stays out entirely, so twenty
    throw the same fifteen.
    """
    spearmen = REPO.units["elven-spearmen"]  # A1, Regular Infantry (5 wide)
    three_ranks = strike_unit(
        _fielded(spearmen, 15).wielding("Thrusting Spear"), _fielded(spearmen, 40)
    )
    assert three_ranks.attacks == 15  # two full ranks (10) + one supporting rank (5)

    four_ranks = strike_unit(
        _fielded(spearmen, 20).wielding("Thrusting Spear"), _fielded(spearmen, 40)
    )
    assert four_ranks.attacks == 15  # the fourth rank neither fights nor supports


def test_strike_unit_supporting_models_strike_at_one_attack_each() -> None:
    """A supporting-rank model makes one attack, whatever its Attacks value.

    A2 spearmen three ranks deep: the front two ranks (ten models) strike at
    A2 for twenty, and the supporting third rank (five models) adds one each —
    twenty-five, not thirty.
    """
    spearmen = REPO.units["elven-spearmen"]
    two_attacks = spearmen.model_copy(deep=True)
    two_attacks.profiles[0].characteristics[Characteristic.ATTACKS] = 2
    result = strike_unit(
        _fielded(two_attacks, 15).wielding("Thrusting Spear"), _fielded(spearmen, 40)
    )
    assert result.attacks == 25  # 10 * 2 (two full ranks) + 5 * 1 (one supporting rank)


def test_strike_unit_press_of_battle_lapses_on_a_charge() -> None:
    """A charging unit forgoes Press of Battle — its front rank alone fights.

    Ten stationary spearmen fight two ranks (ten attacks); the same ten
    charging fight one (five). The attack count is the tell: Press of Battle
    is off on the charge turn.
    """
    spearmen = REPO.units["elven-spearmen"]
    charging = (
        _fielded(spearmen, 10).charging(Charge(3, ChargeArc.FRONT)).wielding("Thrusting Spear")
    )
    result = strike_unit(charging, _fielded(spearmen, 40))
    assert result.attacks == 5  # the front rank only


def test_strike_unit_rejects_a_missile_only_weapon() -> None:
    """A weapon with no Combat profile cannot be used to fight."""
    archers = REPO.units["elven-archers"]
    with pytest.raises(ValueError, match="no Combat profile"):
        strike_unit(_fielded(archers, 5).wielding("Longbow"), _fielded(archers, 10))


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
    spearmen = REPO.units["elven-spearmen"]
    side = _fielded(spearmen, 1)
    result = fight(side.wielding("Thrusting Spear"), side.wielding("Thrusting Spear"))
    assert result.first_striker is None
    assert result.a_casualties[1] == pytest.approx(1 / 6)
    assert result.b_casualties[1] == pytest.approx(1 / 6)


def test_fight_higher_initiative_strikes_first_and_takes_less() -> None:
    """A strikes first (I10 vs I4); B's survivors strike back with fewer models.

    1 vs 1: A's blow removes B on 1/6, so B swings back only when it
    survived (5/6) and then removes A on 1/6 -> A falls on 5/36. B, hit at
    full strength, falls on 1/6.
    """
    spearmen = REPO.units["elven-spearmen"]
    faster = _fielded(_higher_initiative(spearmen), 1).wielding("Thrusting Spear")
    slower = _fielded(spearmen, 1).wielding("Thrusting Spear")
    result = fight(faster, slower)
    assert result.first_striker is faster
    assert result.b_casualties[1] == pytest.approx(1 / 6)  # A full-strength
    assert result.a_casualties[1] == pytest.approx(5 / 36)  # B struck back reduced


def test_fight_orients_the_joint_to_the_arguments() -> None:
    """When the second argument strikes first, losses stay keyed to (a, b)."""
    spearmen = REPO.units["elven-spearmen"]
    slower = _fielded(spearmen, 1).wielding("Thrusting Spear")
    faster = _fielded(_higher_initiative(spearmen), 1).wielding("Thrusting Spear")
    result = fight(slower, faster)
    assert result.first_striker is faster
    # b (faster) strikes first at full strength -> a falls on 1/6; a's
    # survivors strike back -> b falls on 5/36. Mirror of the test above.
    assert result.a_casualties[1] == pytest.approx(1 / 6)
    assert result.b_casualties[1] == pytest.approx(5 / 36)


def test_fight_coupling_reduces_the_return_strike() -> None:
    """Striking first strictly lowers the expected return damage taken.

    A (I10) vs B (I4), 5 each: some B models die before swinging, so the
    casualties A suffers are fewer than a full-strength B strike would deal.
    """
    spearmen = REPO.units["elven-spearmen"]
    result = fight(
        _fielded(_higher_initiative(spearmen), 5).wielding("Thrusting Spear"),
        _fielded(spearmen, 5).wielding("Thrusting Spear"),
    )
    full_strength = strike_unit(
        _fielded(spearmen, 5).wielding("Thrusting Spear"), _fielded(spearmen, 5)
    )
    assert expected_value(result.a_casualties) < expected_value(full_strength.casualties)


def test_fight_caps_a_deep_spear_unit_at_three_ranks() -> None:
    """Depth past three ranks adds nothing: two fight, one supports, the rest wait.

    Two I4 spear bodies strike simultaneously, so each side's blows land at its
    entering strength (no coupling reduction). Against a defender too large to
    wipe out, a four-rank attacker fells exactly as many as a three-rank one —
    both throw two full ranks plus one supporting rank (Press of Battle + Fight
    in Extra Rank), the fourth rank idle. A two-rank attacker fells fewer: it
    has no third rank to support from.
    """
    spearmen = REPO.units["elven-spearmen"]
    big = _fielded(spearmen, 40)
    four = fight(
        _fielded(spearmen, 20).wielding("Thrusting Spear"), big.wielding("Thrusting Spear")
    )
    three = fight(
        _fielded(spearmen, 15).wielding("Thrusting Spear"), big.wielding("Thrusting Spear")
    )
    two = fight(
        _fielded(spearmen, 10).wielding("Thrusting Spear"), big.wielding("Thrusting Spear")
    )
    assert expected_value(four.b_casualties) == pytest.approx(expected_value(three.b_casualties))
    assert expected_value(three.b_casualties) > expected_value(two.b_casualties)


def test_fight_factors_the_rank_rules_for_both_sides() -> None:
    """Both sides strike, so each side's rank rules are in the math — no note.

    A mirror of stationary spear-armed Regular Infantry: Press of Battle (the
    troop type's) and Fight in Extra Rank (the spear's) are claimed for both
    sides, so neither is left in the round's notes.
    """
    spearmen = REPO.units["elven-spearmen"]
    result = fight(
        _fielded(spearmen, 10).wielding("Thrusting Spear"),
        _fielded(spearmen, 10).wielding("Thrusting Spear"),
    )
    assert not any("Press of Battle" in note for note in result.notes)
    assert not any("Fight In Extra Rank" in note for note in result.notes)


def test_fight_rejects_negative_models() -> None:
    """A negative model count is a programming error, not a silent zero."""
    spearmen = REPO.units["elven-spearmen"]
    with pytest.raises(ValueError, match="model counts must be >= 0"):
        fight(
            _fielded(spearmen, -1).wielding("Thrusting Spear"),
            _fielded(spearmen, 5).wielding("Thrusting Spear"),
        )


# --- fight(): pre-combat losses folded in (a_prior_losses / b_prior_losses) ---


def test_fight_degenerate_prior_losses_equal_a_plain_fight() -> None:
    """A pmf certain no models were lost reproduces the plain-fight joint."""
    spearmen = REPO.units["elven-spearmen"]
    a, b = _fielded(spearmen, 3), _fielded(spearmen, 3)
    plain = fight(a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"))
    with_prior = fight(
        a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"), a_prior_losses=[1.0]
    )
    assert with_prior.losses == plain.losses


def test_fight_prior_losses_mix_the_round_over_entering_strength() -> None:
    """A 50/50 prior on A mixes a full-strength round with an A-absent one.

    1v1 simultaneous spearmen: at full strength each falls independently on
    1/6. If A already lost its one model (prob 1/2) it makes no attack and
    takes none, so all that branch's mass sits at (0, 0). Each side's melee
    loss then halves to 1/12.
    """
    spearmen = REPO.units["elven-spearmen"]
    a, b = _fielded(spearmen, 1), _fielded(spearmen, 1)
    result = fight(
        a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"), a_prior_losses=[0.5, 0.5]
    )
    assert result.a_casualties[1] == pytest.approx(0.5 * 1 / 6)  # only the full branch
    assert result.b_casualties[1] == pytest.approx(0.5 * 1 / 6)
    assert sum(sum(row) for row in result.losses) == pytest.approx(1.0)


def test_fight_prior_losses_reject_more_losses_than_models() -> None:
    """A pmf longer than the side's models + 1 cannot describe its losses."""
    spearmen = REPO.units["elven-spearmen"]
    a, b = _fielded(spearmen, 2), _fielded(spearmen, 2)
    with pytest.raises(ValueError, match="a_prior_losses covers more losses"):
        fight(
            a.wielding("Thrusting Spear"),
            b.wielding("Thrusting Spear"),
            a_prior_losses=[0.25, 0.25, 0.25, 0.25],
        )


def test_fight_prior_losses_reject_a_non_distribution() -> None:
    """A prior-loss pmf that is not a probability distribution is rejected."""
    spearmen = REPO.units["elven-spearmen"]
    a, b = _fielded(spearmen, 2), _fielded(spearmen, 2)
    with pytest.raises(ValueError, match="must sum to 1"):
        fight(
            a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"), b_prior_losses=[0.5, 0.2]
        )


# --- Charge: fed into fight() as the striking-order bonus ---


@pytest.mark.parametrize(
    ("inches", "arc", "expected"),
    [
        (0, ChargeArc.FRONT, 4),  # +0: no full inch moved
        (2, ChargeArc.FRONT, 6),  # +1 per full inch
        (5, ChargeArc.FRONT, 7),  # capped at +3 into the front arc
        (5, ChargeArc.FLANK, 8),  # +4 into the flank
        (5, ChargeArc.REAR, 8),  # +4 into the rear
    ],
)
def test_effective_initiative_applies_the_charge_bonus(
    inches: int, arc: ChargeArc, expected: int
) -> None:
    """+1 Initiative per full inch charged, capped by arc, on the I4 base."""
    spearmen = REPO.units["elven-spearmen"]  # I4
    charger = _fielded(spearmen, 5)
    assert effective_initiative(charger, Charge(inches, arc).initiative_bonus).value == expected


def test_effective_initiative_caps_at_ten() -> None:
    """The charge bonus cannot lift Initiative past the printed cap of 10."""
    fast = _higher_initiative(REPO.units["elven-spearmen"], 9)
    charger = _fielded(fast, 5)
    bonus = Charge(5, ChargeArc.FLANK).initiative_bonus
    assert effective_initiative(charger, bonus).value == 10  # 9 + 4 -> 10


def test_fight_charge_makes_the_charger_strike_first() -> None:
    """A charge flips an equal-Initiative combat: the charger swings first.

    Both units are I4, so a standing fight is simultaneous; a 3" charge lifts
    the charger to I7, so it strikes first and its foe swings back reduced.
    """
    spearmen = REPO.units["elven-spearmen"]
    charger = _fielded(spearmen, 1).charging(Charge(3, ChargeArc.FRONT))
    charger = charger.wielding("Thrusting Spear")
    defender = _fielded(spearmen, 1).wielding("Thrusting Spear")
    result = fight(charger, defender)
    assert result.first_striker is charger
    assert result.b_casualties[1] == pytest.approx(1 / 6)  # charger struck full-strength
    assert result.a_casualties[1] == pytest.approx(5 / 36)  # defender struck back reduced


def test_fight_charge_capped_below_the_foe_stays_simultaneous() -> None:
    """A charge whose bonus does not exceed the foe's Initiative changes no order.

    A 0" charge grants +0, so two I4 units still strike simultaneously — the
    bonus must actually raise Initiative above the foe's to matter.
    """
    spearmen = REPO.units["elven-spearmen"]
    charger = _fielded(spearmen, 1).charging(Charge(0, ChargeArc.FRONT))
    result = fight(
        charger.wielding("Thrusting Spear"),
        _fielded(spearmen, 1).wielding("Thrusting Spear"),
    )
    assert result.first_striker is None


# --- combat_result(): scoring the round on unsaved wounds inflicted ---


def test_combat_result_first_strike_advantage() -> None:
    """Striking first tilts the win split (1v1, A at I10).

    A always swings full; B swings back only if it lived (5/6). Joint:
    P(A wins) = P(B falls, A lives) = 1/6; P(B wins) = P(A falls) =
    5/6 * 1/6 = 5/36; the rest (25/36) is a draw.
    """
    spearmen = REPO.units["elven-spearmen"]
    result = fight(
        _fielded(_higher_initiative(spearmen), 1).wielding("Thrusting Spear"),
        _fielded(spearmen, 1).wielding("Thrusting Spear"),
    )
    cr = combat_result(result)
    assert cr.p_a_wins == pytest.approx(1 / 6)
    assert cr.p_b_wins == pytest.approx(5 / 36)
    assert cr.p_draw == pytest.approx(25 / 36)
    assert cr.margin[1] == pytest.approx(6 / 36)  # A ahead by one wound
    assert cr.margin[-1] == pytest.approx(5 / 36)  # B ahead by one wound
    assert sum(cr.margin.values()) == pytest.approx(1.0)


def test_combat_result_adds_the_rank_bonus_to_the_score() -> None:
    """A side's Rank Bonus shifts every combat-result lead by that constant.

    With a symmetric loss joint the plain result is even; giving A +2 and
    B +0 shifts every margin up by 2, so A wins outright.
    """
    losses = [[0.25, 0.25], [0.25, 0.25]]  # symmetric: each side loses 0 or 1
    plain = combat_result(FightResult(losses=losses, first_striker=None))
    ranked = combat_result(
        FightResult(losses=losses, first_striker=None, a_rank_bonus=2, b_rank_bonus=0)
    )
    assert plain.p_a_wins == pytest.approx(plain.p_b_wins)
    assert {lead + 2: mass for lead, mass in plain.margin.items()} == ranked.margin
    assert ranked.p_a_wins == pytest.approx(1.0)


def test_combat_result_simultaneous_is_symmetric() -> None:
    """Equal Initiative: the win split is symmetric between the two sides."""
    spearmen = REPO.units["elven-spearmen"]
    side = _fielded(spearmen, 1)
    cr = combat_result(fight(side.wielding("Thrusting Spear"), side.wielding("Thrusting Spear")))
    assert cr.p_a_wins == pytest.approx(cr.p_b_wins)
    assert cr.p_a_wins == pytest.approx(5 / 36)
    assert cr.p_draw == pytest.approx(26 / 36)


def test_combat_result_adds_the_combat_result_bonus_to_the_score() -> None:
    """A rule-granted combat-result point shifts every lead, like the Rank Bonus.

    Giving A +1 combat-result point and B +0 shifts every margin up by one —
    the engine sums the point without caring which rule granted it.
    """
    losses = [[0.25, 0.25], [0.25, 0.25]]  # symmetric: each side loses 0 or 1
    plain = combat_result(FightResult(losses=losses, first_striker=None))
    bonused = combat_result(
        FightResult(
            losses=losses, first_striker=None, a_combat_result_bonus=1, b_combat_result_bonus=0
        )
    )
    assert {lead + 1: mass for lead, mass in plain.margin.items()} == bonused.margin


# --- Massed Infantry: the outnumbering side's +1 combat result, from data/ ---


def test_fight_massed_infantry_bonuses_the_side_with_higher_unit_strength() -> None:
    """The side with the higher Unit Strength claims Massed Infantry's +1.

    Two Regular Infantry bodies (both carry Massed Infantry at US 1 per model)
    of different sizes: the larger outnumbers, so its combat-result bonus is +1
    and the smaller's is 0 — it has the rule but not the higher Unit Strength.
    Both sides evaluate the rule, so neither leaves it noted.
    """
    spearmen = REPO.units["elven-spearmen"]
    big = _fielded(spearmen, 10).wielding("Thrusting Spear")
    small = _fielded(spearmen, 5).wielding("Thrusting Spear")
    result = fight(big, small)
    assert (result.a_unit_strength, result.b_unit_strength) == (10, 5)
    assert result.a_combat_result_bonus == 1
    assert result.b_combat_result_bonus == 0
    assert not any("Massed Infantry" in note for note in result.notes)


def test_fight_massed_infantry_needs_a_strictly_higher_unit_strength() -> None:
    """Equal Unit Strength outnumbers neither side, so no one claims the +1."""
    spearmen = REPO.units["elven-spearmen"]
    side = _fielded(spearmen, 5).wielding("Thrusting Spear")
    result = fight(side, _fielded(spearmen, 5).wielding("Thrusting Spear"))
    assert (result.a_combat_result_bonus, result.b_combat_result_bonus) == (0, 0)
    assert not any("Massed Infantry" in note for note in result.notes)  # honoured, still claimed


# --- rule-granted Initiative modifiers, consumed through the loadout ---


def _reflexive(unit: Unit) -> Contingent:
    # A deployed-style contingent whose one rule grants +1 Initiative in
    # the first round of combat: the loadout built directly, the rule a
    # double for any characteristic-modifier rule.
    rule = Rule(
        id="doctored-reflexes",
        name="Doctored Reflexes",
        paragraphs=["…"],
        effects=[
            ModifierEffect(
                when={Condition.FIRST_ROUND_OF_COMBAT: True},
                add={Characteristic.INITIATIVE: 1},
                maximum=10,
            )
        ],
    )
    doctored = unit.model_copy(update={"special_rules": ["Doctored Reflexes"]})
    spear = REPO.weapons["thrusting-spear"]
    return Contingent(doctored, 1, Loadout((spear,), (), (rule,), ()), frontage=1)


def test_fight_first_round_initiative_rule_flips_the_order() -> None:
    """In the combat's first round the rule-bearer strikes first.

    Two I4 spearmen bodies strike simultaneously; the +1 first-round
    modifier lifts one side to I5, so it strikes first — and its rule's
    "not factored" note disappears, because the rule is in the math.
    The foe is fielded without its printed rules, so the real Elven
    Reflexes in data cannot hand it the same +1.
    """
    spearmen = REPO.units["elven-spearmen"]
    quick = _reflexive(spearmen).wielding("Thrusting Spear")
    result = fight(
        quick,
        _fielded(spearmen.model_copy(update={"special_rules": []}), 1).wielding("Thrusting Spear"),
        first_round=True,
    )
    assert result.first_striker is quick
    assert not any("Doctored Reflexes" in note for note in result.notes)


def test_fight_later_round_initiative_rule_is_honoured_by_not_applying() -> None:
    """Past the first round the modifier grants nothing — and is not noted."""
    spearmen = REPO.units["elven-spearmen"]
    result = fight(
        _reflexive(spearmen).wielding("Thrusting Spear"),
        _fielded(spearmen, 1).wielding("Thrusting Spear"),
        first_round=False,
    )
    assert result.first_striker is None
    assert not any("Doctored Reflexes" in note for note in result.notes)


def test_fight_unknown_round_leaves_the_rule_noted() -> None:
    """Without the round fact the modifier cannot be evaluated: unfactored."""
    spearmen = REPO.units["elven-spearmen"]
    result = fight(
        _reflexive(spearmen).wielding("Thrusting Spear"),
        _fielded(spearmen, 1).wielding("Thrusting Spear"),
    )
    assert result.first_striker is None
    assert any("Doctored Reflexes" in note for note in result.notes)


# --- Strike First / Strike Last: Initiative set, before other modifiers ---


def _carrying(*rule_ids: str) -> Contingent:
    # A deployed-style spearman carrying real special rules from data, attached
    # to its loadout and named on the unit so their notes reconcile — the
    # Strike First / Strike Last shape, rules the Initiative read consumes.
    rules = tuple(REPO.rules[rid] for rid in rule_ids)
    unit = REPO.units["elven-spearmen"].model_copy(
        update={"special_rules": [r.name for r in rules]}
    )
    spear = REPO.weapons["thrusting-spear"]
    return Contingent(unit, 1, Loadout((spear,), (), rules, ()), frontage=1).wielding(
        "Thrusting Spear"
    )


def _plain_spearman() -> Contingent:
    # The symmetric foe: elven-spearmen (Initiative 4) with its printed rules
    # stripped, so nothing of its own touches the Initiative comparison.
    bare = REPO.units["elven-spearmen"].model_copy(update={"special_rules": []})
    return _fielded(bare, 1).wielding("Thrusting Spear")


def test_effective_initiative_strike_first_sets_ten() -> None:
    """Strike First replaces Initiative with 10, and the rule is factored."""
    ei = effective_initiative(_carrying("strike-first"), 0, {})
    assert ei.value == 10
    assert "Strike First" in ei.factored


def test_effective_initiative_strike_last_sets_one_before_the_charge() -> None:
    """Strike Last replaces Initiative with 1 before the charge bonus is added.

    The set lands first, so a +1 charge bonus lifts the 1 to 2 — not the base 4
    to 5. This is the "before any other modifiers are applied" clause.
    """
    ei = effective_initiative(_carrying("strike-last"), 1, {})
    assert ei.value == 2
    assert "Strike Last" in ei.factored


def test_effective_initiative_strike_first_and_last_cancel() -> None:
    """Carrying both rules, the two sets cancel and the base Initiative stands.

    Both are still honoured (factored) — the printed "cancel one another out",
    modelled as two disagreeing sets washing out.
    """
    ei = effective_initiative(_carrying("strike-first", "strike-last"), 0, {})
    assert ei.value == 4  # the printed elven-spearmen Initiative
    assert set(ei.factored) >= {"Strike First", "Strike Last"}


def test_fight_strike_first_strikes_before_the_foe() -> None:
    """A Strike First model strikes first; its rule is in the math, so unnoted."""
    quick = _carrying("strike-first")
    result = fight(quick, _plain_spearman(), first_round=True)
    assert result.first_striker is quick
    assert not any("Strike First" in note for note in result.notes)


def test_fight_strike_last_yields_the_first_blows() -> None:
    """A Strike Last model strikes last; the faster foe strikes first."""
    slow = _carrying("strike-last")
    foe = _plain_spearman()
    result = fight(slow, foe, first_round=True)
    assert result.first_striker is foe
    assert not any("Strike Last" in note for note in result.notes)


def test_fight_strike_first_and_last_cancel_to_simultaneous() -> None:
    """Both rules cancel: equal Initiative with the mirror foe strikes at once.

    Neither note is reported — both are honoured (factored), just to no effect.
    """
    result = fight(_carrying("strike-first", "strike-last"), _plain_spearman(), first_round=True)
    assert result.first_striker is None
    assert not any("Strike First" in note or "Strike Last" in note for note in result.notes)


# --- Strike Last from the weapon in hand: the great-weapon route ---


def _strike_last_weapon() -> Weapon:
    # A doctored great weapon whose Combat profile carries Strike Last — a
    # synthetic stand-in for the Chracian Great Blade, so the routing test does
    # not lean on any imported army data.
    spear = REPO.weapons["thrusting-spear"]
    combat = spear.combat_profile
    assert combat is not None  # the thrusting spear is a Combat weapon
    profile = combat.model_copy(update={"special_rules": ["Strike Last"]})
    return spear.model_copy(
        update={
            "id": "doctored-blade",
            "name": "Doctored Blade",
            "profiles": [profile],
            "notes": None,
        }
    )


def _wielding_strike_last(*unit_rule_ids: str) -> Contingent:
    # An elven spearman wielding the Strike-Last blade, optionally also carrying
    # unit rules (to test the unit-and-weapon cancellation). The weapon's Strike
    # Last resolves through the loadout's weapon-rule index.
    rules = tuple(REPO.rules[rid] for rid in unit_rule_ids)
    unit = REPO.units["elven-spearmen"].model_copy(
        update={"special_rules": [r.name for r in rules]}
    )
    weapon_rules = {"Strike Last": REPO.rules["strike-last"]}
    loadout = Loadout((_strike_last_weapon(),), (), rules, (), weapon_rules)
    return Contingent(unit, 1, loadout, frontage=1).wielding("Doctored Blade")


def test_effective_initiative_reads_a_strike_last_weapon() -> None:
    """Strike Last on the weapon in hand reaches the Initiative read.

    The rule rides on the great weapon's Combat profile, not the unit, yet it
    sets the wielder's Initiative to 1 — folded through in_hand_rules and
    factored, never left as an unfactored weapon note.
    """
    ei = effective_initiative(_wielding_strike_last(), 0, {})
    assert ei.value == 1
    assert "Strike Last" in ei.factored


def test_fight_strike_last_weapon_yields_the_first_blows() -> None:
    """A wielder of a Strike-Last weapon strikes last; the weapon note is claimed."""
    slow = _wielding_strike_last()
    foe = _plain_spearman()
    result = fight(slow, foe, first_round=True)
    assert result.first_striker is foe
    assert result.a_initiative.value == 1
    assert not any("Strike Last" in note for note in result.notes)


def test_fight_unit_strike_first_and_weapon_strike_last_cancel() -> None:
    """Strike First on the unit and Strike Last on the weapon cancel across pools.

    The two sources fold together, so a Strike First model wielding a Strike
    Last weapon has neither apply — the base Initiative (4) stands, both factored.
    """
    ei = effective_initiative(_wielding_strike_last("strike-first"), 0, {})
    assert ei.value == 4
    assert set(ei.factored) >= {"Strike First", "Strike Last"}


# --- Furious Charge: +1 Attacks on the charge ---


def test_effective_attacks_furious_charge_adds_on_the_charge() -> None:
    """Furious Charge lifts the Attacks characteristic by one on a charging turn."""
    charging = _carrying("furious-charge").charging(Charge(6, ChargeArc.FRONT))
    attacks = charging.effective_attacks()
    assert attacks.value == 2  # base A1 + 1
    assert "Furious Charge" in attacks.factored


def test_effective_attacks_furious_charge_honoured_while_standing() -> None:
    """Standing still, Furious Charge grants nothing — honoured, still factored."""
    attacks = _carrying("furious-charge").effective_attacks()
    assert attacks.value == 1
    assert "Furious Charge" in attacks.factored


def test_melee_attacks_grow_with_furious_charge() -> None:
    """The fighting rank throws its Furious-Charge Attacks: one more on the charge."""
    charging = _carrying("furious-charge").charging(Charge(6, ChargeArc.FRONT))
    standing = _carrying("furious-charge")
    assert charging.melee_attacks() == standing.melee_attacks() + 1


def test_fight_furious_charge_is_factored_not_noted() -> None:
    """A charging model's Furious Charge is in the math, so it leaves no note."""
    charging = _carrying("furious-charge").charging(Charge(6, ChargeArc.FRONT))
    result = fight(charging, _plain_spearman(), first_round=True)
    assert not any("Furious Charge" in note for note in result.notes)


# --- Elven Reflexes, end to end from data/ ---


def _deployed(slug: str, models: int) -> Contingent:
    return _fielded(REPO.units[slug], models)


def test_elven_reflexes_strikes_first_in_the_first_round() -> None:
    """The data-driven +1 Initiative decides the order against a slower foe.

    Deployed spearmen (I4, Elven Reflexes) against a doctored body of
    the same profile without the rule: simultaneous in any later round,
    but in the first round the elves strike at I5 and swing first. The
    factored rule leaves no "not factored" note.
    """
    spearmen = REPO.units["elven-spearmen"]
    elves = _deployed("elven-spearmen", 5).wielding("Thrusting Spear")
    base = spearmen.profiles[0][Characteristic.INITIATIVE]
    foe = _fielded(spearmen.model_copy(update={"special_rules": []}), 5)
    first = fight(
        elves,
        foe.wielding("Thrusting Spear"),
        first_round=True,
    )
    later = fight(
        elves,
        foe.wielding("Thrusting Spear"),
        first_round=False,
    )
    assert base is not None
    assert first.a_initiative.value == base + 1
    assert first.first_striker is elves
    assert not any("Elven Reflexes" in note for note in first.notes)
    assert later.a_initiative.value == base
    assert later.first_striker is None
    assert not any("Elven Reflexes" in note for note in later.notes)


def test_elven_reflexes_unknown_round_stays_noted() -> None:
    """Without the round fact the rule cannot be evaluated: noted, no bonus."""
    elves = _deployed("elven-spearmen", 5)
    result = fight(
        elves.wielding("Thrusting Spear"),
        _deployed("elven-spearmen", 5).wielding("Thrusting Spear"),
    )
    assert result.first_striker is None
    assert any("Elven Reflexes" in note for note in result.notes)


def test_charge_factors_elven_reflexes_structurally() -> None:
    """A charge is a combat's first round, so both elven sides gain the +1.

    Deployed spearmen charge deployed archers 3": the mirror-image +1
    cancels in the order (charge bonus still decides it), and neither
    side's Elven Reflexes is left in the notes — the rule is in the math.
    """
    from avelorn.tow.phases.movement import charge

    engagement = charge(
        _deployed("elven-spearmen", 5).wielding("Thrusting Spear"),
        _deployed("elven-archers", 5).wielding("Hand Weapon"),
        Charge(3, ChargeArc.FRONT),
        shooting_rules=IN_FORCE,
    )
    melee = COMBAT.fight(engagement)
    assert melee.a_initiative.value == melee.b_initiative.value + 3  # charge bonus only
    assert not any("Elven Reflexes" in note for note in melee.notes)


def test_first_round_flag_governs_the_first_round_rules() -> None:
    """CombatPhase.fight reads first_round off the engagement.

    Elven Reflexes grants +1 Initiative only in the first round of combat, so
    the charger's Initiative is one higher for the charge's first round than
    for a later round of the same engagement (after end_turn) — the charge
    bonus, which comes from the move, applies in both.
    """
    from avelorn.tow.phases.movement import charge

    move = Charge(3, ChargeArc.FRONT)

    fresh_engagement = charge(
        _deployed("elven-spearmen", 5).wielding("Thrusting Spear"),
        _deployed("elven-archers", 5).wielding("Hand Weapon"),
        move,
        shooting_rules=IN_FORCE,
    )
    fresh = COMBAT.fight(fresh_engagement)

    later_engagement = charge(
        _deployed("elven-spearmen", 5).wielding("Thrusting Spear"),
        _deployed("elven-archers", 5).wielding("Hand Weapon"),
        move,
        shooting_rules=IN_FORCE,
    )
    later_engagement.end_turn()
    later = COMBAT.fight(later_engagement)

    assert fresh.a_initiative.value == later.a_initiative.value + 1


# --- Martial Prowess, the +1 Weapon Skill in the first round, from data/ ---


def test_effective_weapon_skill_gains_one_in_the_first_round() -> None:
    """Martial Prowess lifts Weapon Skill by one, and only in the first round.

    The data-driven +1 WS is read for the first round, honoured as a no-op in
    a later round (factored, no change), and left unfactored when the round is
    unknown — the same three dispositions the Initiative query reports.
    """
    spearmen = REPO.units["elven-spearmen"]  # WS4, Martial Prowess
    elves = _fielded(spearmen, 5)
    base = spearmen.profiles[0][Characteristic.WEAPON_SKILL]
    assert base is not None

    first = effective_weapon_skill(elves, {Condition.FIRST_ROUND_OF_COMBAT: True})
    assert first.value == base + 1
    assert "Martial Prowess" in first.factored

    later = effective_weapon_skill(elves, {Condition.FIRST_ROUND_OF_COMBAT: False})
    assert later.value == base
    assert "Martial Prowess" in later.factored  # honoured by not applying

    unknown = effective_weapon_skill(elves)  # no round fact
    assert unknown.value == base
    assert "Martial Prowess" in unknown.unfactored


def _only_martial_prowess(unit: Unit) -> Unit:
    # The unit stripped to Martial Prowess alone, so equal Initiative keeps the
    # blows simultaneous and uncoupled — the WS change is the only asymmetry.
    return unit.model_copy(update={"special_rules": ["Martial Prowess"]})


def test_fight_first_round_martial_prowess_sharpens_both_sides() -> None:
    """The +1 WS reaches the dice for the striker and, as target WS, against it.

    A body carrying only Martial Prowess against a plain copy of itself, at
    equal Initiative (simultaneous, uncoupled): in the first round it strikes
    at WS5 and fells more of the foe than in a later round at WS4, and — its
    raised WS being the target the foe rolls against — it also loses fewer of
    its own. The factored rule leaves no "not factored" note in either round,
    the later round honouring it as a no-op.
    """
    spearmen = REPO.units["elven-spearmen"]
    elves = _fielded(_only_martial_prowess(spearmen), 5).wielding("Thrusting Spear")
    foe = _fielded(spearmen.model_copy(update={"special_rules": []}), 5).wielding(
        "Thrusting Spear"
    )

    first = fight(elves, foe, first_round=True)
    later = fight(elves, foe, first_round=False)

    assert first.first_striker is None and later.first_striker is None  # equal I4
    assert expected_value(first.b_casualties) > expected_value(later.b_casualties)  # striker WS
    assert expected_value(first.a_casualties) < expected_value(later.a_casualties)  # target WS
    assert not any("Martial Prowess" in note for note in first.notes)
    assert not any("Martial Prowess" in note for note in later.notes)


def test_fight_unknown_round_leaves_martial_prowess_noted() -> None:
    """Without the round fact the +1 WS cannot be evaluated: noted, no bonus."""
    spearmen = REPO.units["elven-spearmen"]
    elves = _fielded(_only_martial_prowess(spearmen), 5).wielding("Thrusting Spear")
    foe = _fielded(spearmen.model_copy(update={"special_rules": []}), 5).wielding(
        "Thrusting Spear"
    )
    result = fight(elves, foe)  # first round unknown
    assert any("Martial Prowess" in note for note in result.notes)


# --- combat chapter rules in force, factored into the strike ---


def _combat_chapter_rule(name: str, when: dict | None = None) -> Rule:
    # A Combat-phase chapter rule granting +1 To Hit: a double for any
    # rule the chapter puts in force, factored into every strike under it.
    return Rule(
        id="doctored-combat-rule",
        name=name,
        paragraphs=["…"],
        category=Phase.COMBAT,
        effects=[ModifierEffect(when=when, add={Quantity.TO_HIT: 1})],
    )


def test_fight_factors_a_combat_chapter_rule() -> None:
    """A combat chapter rule in force reaches the strike's dice.

    An unconditional +1 To Hit, passed as ``phase_rules``, lifts both
    sides' hit rolls, so each inflicts more casualties than the same fight
    with no rule in force — and it leaves no "core rule not factored"
    note, because it is in the math. This is the seam: a combat chapter
    rule gaining effects is honoured, no new code.
    """
    spearmen = REPO.units["elven-spearmen"]
    a, b = _fielded(spearmen, 5), _fielded(spearmen, 5)
    rule = _combat_chapter_rule("Doctored Combat Rule")
    plain = fight(a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"))
    in_force = fight(
        a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"), phase_rules={rule.name: rule}
    )
    assert expected_value(in_force.a_casualties) > expected_value(plain.a_casualties)
    assert expected_value(in_force.b_casualties) > expected_value(plain.b_casualties)
    assert not any("core rule" in note for note in in_force.notes)


def test_fight_leaves_an_unanswerable_combat_rule_noted() -> None:
    """A combat chapter rule the conditions cannot answer stays noted.

    Conditioned on the first round of combat but fought without that
    fact: the modifier is not in the math (casualties match the plain
    fight) and the rule is reported "core rule not factored", never
    silently dropped.
    """
    spearmen = REPO.units["elven-spearmen"]
    a, b = _fielded(spearmen, 5), _fielded(spearmen, 5)
    rule = _combat_chapter_rule(
        "Doctored First-Round Rule", when={Condition.FIRST_ROUND_OF_COMBAT: True}
    )
    plain = fight(a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"))
    noted = fight(
        a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"), phase_rules={rule.name: rule}
    )
    assert noted.a_casualties == plain.a_casualties
    assert noted.b_casualties == plain.b_casualties
    assert any("core rule not factored: Doctored First-Round Rule" in n for n in noted.notes)
