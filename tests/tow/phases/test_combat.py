"""Close-combat strike tests, golden values hand-computed from the charts."""

from fractions import Fraction

import pytest

from avelorn.core.dice import binomial_distribution, expected_value
from avelorn.tow.contingent import Charge, ChargeArc, Contingent, Loadout
from avelorn.tow.data import TOWRepository
from avelorn.tow.engine.rules import GateContext
from avelorn.tow.phases.combat import (
    CombatPhase,
    FightResult,
    combat_result,
    effective_initiative,
    fight,
    mount_initiative,
    strike,
    strike_unit,
)
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import Bounded, ModifierEffect, Quantity, Rule, WeaponGate, When
from avelorn.tow.schema.unit import Characteristic, ProfileRole, Unit
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


def test_fight_claims_parry_for_an_unarmoured_side_too() -> None:
    """An unarmoured side's Parry is spoken for by the armour fold, not reported.

    Elven Archers wear nothing, so there is no save for their troop type's Parry
    to better — but the fold still reads its disposition (it names a shield they
    cannot be wearing), so a fight leaves no "not factored" note. Skipping the
    fold for want of a base would leave the rule unclaimed by any seam.
    """
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    result = fight(
        _fielded(archers, 5).wielding("Hand Weapon"),
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


def test_strike_unit_leaves_a_fourth_rank_out() -> None:
    """A fourth rank of spears neither fights nor supports: twenty throw what fifteen do."""
    spearmen = REPO.units["elven-spearmen"]
    three_ranks = strike_unit(
        _fielded(spearmen, 15).wielding("Thrusting Spear"), _fielded(spearmen, 40)
    )
    four_ranks = strike_unit(
        _fielded(spearmen, 20).wielding("Thrusting Spear"), _fielded(spearmen, 40)
    )
    assert four_ranks.attacks == three_ranks.attacks


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
    """A pmf certain no models were lost reproduces the plain-fight joint.

    Compared to tolerance, not bit-for-bit: a plain fight is exact throughout,
    while an explicit ``[1.0]`` is an inexact weight and turns the round's masses
    into floats. Numerically the same round, in the two numeric kinds.
    """
    spearmen = REPO.units["elven-spearmen"]
    a, b = _fielded(spearmen, 3), _fielded(spearmen, 3)
    plain = fight(a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"))
    with_prior = fight(
        a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"), a_prior_losses=[1.0]
    )
    for got, want in zip(with_prior.losses, plain.losses, strict=True):
        assert list(got) == pytest.approx([float(p) for p in want])


def test_fight_an_exact_degenerate_prior_keeps_the_round_exact() -> None:
    """An integer-1 prior is exact, so it reproduces the plain joint bit-for-bit."""
    spearmen = REPO.units["elven-spearmen"]
    a, b = _fielded(spearmen, 3), _fielded(spearmen, 3)
    plain = fight(a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"))
    with_prior = fight(
        a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"), a_prior_losses=[1]
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


def test_the_rank_bonus_is_counted_from_the_survivors() -> None:
    """A rank broken by this round's casualties claims no Rank Bonus.

    Ten spearmen five wide claim +1 as the round begins, but any loss leaves a
    rear rank of four, too few to count. So the bonus adds to the score exactly
    when they lose nobody. The foe is one rank of ten: no bonus, equal Unit
    Strength.
    """
    spearmen = REPO.units["elven-spearmen"]
    fought = fight(
        _fielded(spearmen, 10, frontage=5).wielding("Thrusting Spear"),
        _fielded(spearmen, 10, frontage=10).wielding("Thrusting Spear"),
    )
    scored = sum(lead * mass for lead, mass in combat_result(fought).margin.items())
    wounds = sum(diff * mass for diff, mass in fought.scoring_wounds.items())
    assert fought.a_rank_bonus == 1
    assert scored - wounds == pytest.approx(fought.a_casualties[0])
    assert fought.a_casualties[0] < 1


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


def test_stand_and_shoot_wounds_score_for_the_shooting_side() -> None:
    """A Stand & Shoot's wounds count toward the shooter's combat result.

    The charger A enters melee having certainly lost its one model to the
    defender B's volley (a prior loss). Those wounds credit B — the rulebook
    counts a Stand & Shoot's unsaved wounds toward the shooting side — so B
    wins the round outright by that one wound, though no melee blow is struck.
    """
    spearmen = REPO.units["elven-spearmen"]
    a, b = _fielded(spearmen, 1), _fielded(spearmen, 1)
    result = fight(
        a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"), a_prior_losses=[0.0, 1.0]
    )
    cr = combat_result(result)
    assert cr.p_b_wins == pytest.approx(1.0)
    assert cr.p_a_wins == pytest.approx(0.0)
    assert cr.margin[-1] == pytest.approx(1.0)  # B ahead by its one volley wound


def test_stand_and_shoot_credit_tilts_the_result_toward_the_shooter() -> None:
    """A chance of a volley wound tilts an otherwise symmetric round to the shooter.

    Against the symmetric 1v1 baseline (each side wins 5/36), giving A a 50%
    chance of having lost its model to B's Stand & Shoot lifts B's win chance
    above A's — the volley's wounds score for B, correlated with the thinning.
    """
    spearmen = REPO.units["elven-spearmen"]
    a, b = _fielded(spearmen, 1), _fielded(spearmen, 1)
    baseline = combat_result(fight(a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear")))
    with_volley = combat_result(
        fight(
            a.wielding("Thrusting Spear"),
            b.wielding("Thrusting Spear"),
            a_prior_losses=[0.5, 0.5],
        )
    )
    assert baseline.p_a_wins == pytest.approx(baseline.p_b_wins)
    assert with_volley.p_b_wins > with_volley.p_a_wins


# --- the arc a charge struck: the combat-result points it claims ---


def test_fight_scores_the_arc_only_for_the_side_that_charged_it() -> None:
    """The charger claims its arc's points; the side it struck claims none.

    A flank charge is +1 to the charger. Its target charged nothing, so it
    scores no arc of its own, whichever arc it was hit in.
    """
    spearmen = REPO.units["elven-spearmen"]
    charger = (
        _fielded(spearmen, 5).wielding("Thrusting Spear").charging(Charge(6, ChargeArc.FLANK))
    )
    result = fight(charger, _fielded(spearmen, 5).wielding("Thrusting Spear"))
    assert (result.a_combat_result_bonus, result.b_combat_result_bonus) == (1, 0)


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
                when=When.model_validate({"combat": {"first_round": True}}),
                add={Characteristic.INITIATIVE: Bounded(amount=1, maximum=10)},
            )
        ],
    )
    doctored = unit.model_copy(update={"special_rules": [RuleRef(rule=rule.id)]})
    spear = REPO.weapons["thrusting-spear"]
    return Contingent(
        doctored, 1, Loadout.carrying((spear,), (), (rule,), rules=REPO.rules), frontage=1
    )


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
        update={"special_rules": [RuleRef(rule=r.id) for r in rules]}
    )
    spear = REPO.weapons["thrusting-spear"]
    loadout = Loadout.carrying((spear,), (), rules, rules=REPO.rules)
    return Contingent(unit, 1, loadout, frontage=1).wielding("Thrusting Spear")


def _plain_spearman() -> Contingent:
    # The symmetric foe: elven-spearmen (Initiative 4) with its printed rules
    # stripped, so nothing of its own touches the Initiative comparison.
    bare = REPO.units["elven-spearmen"].model_copy(update={"special_rules": []})
    return _fielded(bare, 1).wielding("Thrusting Spear")


def test_effective_initiative_strike_first_and_last_cancel() -> None:
    """Carrying both rules, the two sets cancel and the base Initiative stands.

    Both are still honoured (factored) — the printed "cancel one another out",
    modelled as two disagreeing sets washing out.
    """
    ei = effective_initiative(_carrying("strike-first", "strike-last"), 0, GateContext())
    assert ei.value == 4  # the printed elven-spearmen Initiative
    assert set(ei.factored) >= {"Strike First", "Strike Last"}


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
    profile = combat.model_copy(update={"special_rules": [RuleRef(rule="strike-last")]})
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
        update={"special_rules": [RuleRef(rule=r.id) for r in rules]}
    )
    loadout = Loadout.carrying((_strike_last_weapon(),), (), rules, rules=REPO.rules)
    return Contingent(unit, 1, loadout, frontage=1).wielding("Doctored Blade")


def test_fight_unit_strike_first_and_weapon_strike_last_cancel() -> None:
    """Strike First on the unit and Strike Last on the weapon cancel across pools.

    The two sources fold together, so a Strike First model wielding a Strike
    Last weapon has neither apply — the base Initiative (4) stands, both factored.
    """
    ei = effective_initiative(_wielding_strike_last("strike-first"), 0, GateContext())
    assert ei.value == 4
    assert set(ei.factored) >= {"Strike First", "Strike Last"}


# --- Furious Charge: +1 Attacks on the charge ---


def test_fight_furious_charge_is_factored_not_noted() -> None:
    """A charging model's Furious Charge is in the math, so it leaves no note."""
    charging = _carrying("furious-charge").charging(Charge(6, ChargeArc.FRONT))
    result = fight(charging, _plain_spearman(), first_round=True)
    assert not any("Furious Charge" in note for note in result.notes)


# --- Stomp Attacks / Impact Hits: automatic-hit batches outside the Initiative order ---


def _sword_stomper(*extra_rules: RuleRef) -> Contingent:
    # One armourless spearman with Stomp Attacks (2), swinging the Sword of
    # Hoeth — a magical S+2 blade, so the weapon leg and the weaponless
    # stomps carry different marks.
    unit = REPO.units["elven-spearmen"].model_copy(
        update={
            "special_rules": [RuleRef(rule="stomp-attacks", X=2), *extra_rules],
            "equipment": ["Sword of Hoeth"],
        }
    )
    return _fielded(unit, 1).wielding("Sword of Hoeth")


def _magic_warded_footman() -> Contingent:
    # A bare footman whose one rule grants a 4+ ward against magical attacks
    # only — the mirror of Runes of Protection, built here because no army's
    # data prints one yet.
    rule = Rule(
        id="doctored-magic-ward",
        name="Doctored Magic Ward",
        paragraphs=["…"],
        effects=[
            ModifierEffect(
                when=When.model_validate({"target_of": {"magical": True}}),
                set={Quantity.WARD_SAVE: 4},
            )
        ],
    )
    unit = _foot_unit(initiative=4).model_copy(update={"special_rules": [RuleRef(rule=rule.id)]})
    hand_weapon = REPO.weapons["hand-weapon"]
    loadout = Loadout.carrying((hand_weapon,), (), (rule,), rules=REPO.rules)
    contingent = Contingent(unit, 1, loadout, frontage=1)
    return contingent.wielding("Hand Weapon")


def test_fight_stomps_of_a_magic_sword_bearer_are_not_magical_golden() -> None:
    """The weaponless hits drop the wielded weapon's marks; the weapon leg keeps them.

    A stomper swinging the Sword of Hoeth (magical, S+2) against a footman
    warded 4+ against magical attacks only. The sword leg is magical, so the
    ward stands: hit 4+ (WS4 vs WS4), wound 2+ (S5 vs T3), ward 4+ —
    pw = (1/2)(5/6)(1/2) = 5/24. The foe's blow back fells the armourless
    stomper at (1/2)(1/2) = 1/4, simultaneous at I4. The stomps carry no
    weapon, so they are not magical and the ward never fires: each of the two
    hits fells at the unmodified S3's 1/2, from a stomper the I4 blows spared,
    on a foe still standing:
    P(foe removed) = 5/24 + (19/24)(3/4)(1 - (1/2)^2) = 251/384. Stomps read
    as magical (the bug) would give 5/24 + (19/24)(3/4)(1 - (3/4)^2) =
    719/1536.
    """
    result = fight(_sword_stomper(), _magic_warded_footman())
    assert result.b_casualties[1] == Fraction(251, 384)
    assert result.a_casualties[1] == Fraction(1, 4)


def test_fight_unit_printed_magical_attacks_reaches_the_stomps() -> None:
    """A datasheet's own Magical Attacks marks ALL its attacks, stomps included.

    The same matchup with Magical Attacks printed on the stomper's unit: the
    ward now stands against the stomps too, each felling at (1/2)(1/2) = 1/4 —
    P(foe removed) = 5/24 + (19/24)(3/4)(1 - (3/4)^2) = 719/1536.
    """
    result = fight(_sword_stomper(RuleRef(rule="magical-attacks")), _magic_warded_footman())
    assert result.b_casualties[1] == Fraction(719, 1536)


def test_fight_refuses_automatic_hits_on_a_split_profile_of_differing_strength() -> None:
    """A stomping unit whose mount row prints another Strength is refused loudly.

    Datasheet rules are unit-wide, so "the model making them" cannot be
    named on a split profile: where the rows agree the ambiguity is harmless
    and the fight resolves; where the mount's Strength differs, resolving at
    the rank and file's row would be silently wrong, so the fight raises.
    """
    stomping = _cavalry_unit(rider_i=5, mount_i=3).model_copy(
        update={"special_rules": [RuleRef(rule="stomp-attacks", X=2)]}
    )
    differing = stomping.model_copy(
        update={
            "profiles": [
                row
                if row.role is not ProfileRole.MOUNT
                else row.model_copy(
                    update={
                        "characteristics": {
                            **row.characteristics,
                            Characteristic.STRENGTH: 5,
                        }
                    }
                )
                for row in stomping.profiles
            ]
        }
    )
    foe = Contingent.field(_foot_unit(initiative=4), 1, data=REPO).wielding("Hand Weapon")

    with pytest.raises(ValueError, match="cannot be attributed"):
        fight(Contingent.field(differing, 1, data=REPO).wielding("Hand Weapon"), foe)

    resolved = fight(Contingent.field(stomping, 1, data=REPO).wielding("Hand Weapon"), foe)
    assert not any("not factored: Stomp Attacks" in note for note in resolved.notes)


# --- Enemy-subject effects: a rule of one side landing on the other's numbers ---


def test_fight_blizzard_aura_cancels_the_foes_strike_first() -> None:
    """An aura's Strike Last on the foe cancels the foe's own Strike First.

    Two disagreeing sets — the foe's own 10 and the aura's enemy-subject 1 —
    wash out in one fold, so the foe's base Initiative stands and the round
    is simultaneous: the printed cancellation, across the two sides' rules.
    """
    result = fight(_carrying("blizzard-aura"), _carrying("strike-first"), first_round=True)
    assert result.b_initiative.value == 4
    assert result.first_striker is None
    assert not any("not factored: Blizzard Aura" in note for note in result.notes)
    assert not any("not factored: Strike First" in note for note in result.notes)


# --- Elven Reflexes, end to end from data/ ---


def _deployed(slug: str, models: int) -> Contingent:
    return _fielded(REPO.units[slug], models)


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


def _only_martial_prowess(unit: Unit) -> Unit:
    # The unit stripped to Martial Prowess alone, so equal Initiative keeps the
    # blows simultaneous and uncoupled — the WS change is the only asymmetry.
    return unit.model_copy(update={"special_rules": [RuleRef(rule="martial-prowess")]})


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
    gate = When.model_validate(when) if when is not None else None
    return Rule(
        id="doctored-combat-rule",
        name=name,
        paragraphs=["…"],
        category=Phase.COMBAT,
        effects=[ModifierEffect(when=gate, add={Quantity.TO_HIT: 1})],
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
        "Doctored First-Round Rule", when={"combat": {"first_round": True}}
    )
    plain = fight(a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"))
    noted = fight(
        a.wielding("Thrusting Spear"), b.wielding("Thrusting Spear"), phase_rules={rule.name: rule}
    )
    assert noted.a_casualties == plain.a_casualties
    assert noted.b_casualties == plain.b_casualties
    assert any("core rule not factored: Doctored First-Round Rule" in n for n in noted.notes)


def _piercing_swordsman(models: int = 1) -> Contingent:
    # A unit rule that worsens its foe's save by 1 while a hand weapon is in
    # hand — the Gromril Weapons shape, built here so the test does not depend
    # on which army's data carries it.
    rule = Rule(
        id="doctored-gromril",
        name="Doctored Gromril",
        paragraphs=["A hand weapon carried by this model has an Armour Piercing of -1."],
        effects=[
            ModifierEffect(
                when=When(wielding=WeaponGate(name="Hand Weapon")),
                add={Quantity.ARMOUR_PIERCING: 1},
            )
        ],
    )
    unit = REPO.units["elven-spearmen"].model_copy(
        update={"special_rules": [RuleRef(rule=rule.id)], "equipment": ["Hand Weapon"]}
    )
    hand_weapon = REPO.weapons["hand-weapon"]
    loadout = Loadout.carrying((hand_weapon,), (), (rule,), rules=REPO.rules)
    contingent = Contingent(unit, models, loadout, frontage=1)
    return contingent.wielding("Hand Weapon")


def test_unit_rule_armour_piercing_reaches_the_melee_walk() -> None:
    """A striker's own rule worsens the target's save, as it does in a volley.

    The melee walk compiled the weapon's rules only, so a unit rule moving
    Armour Piercing was reported unfactored and changed nothing. Striking
    White Lions (5+ Heavy Armour; Lion Cloak is a shooting rule and no-ops
    here), the rule worsens the save to 6+ and is claimed out of the notes.
    """
    lions = _fielded(REPO.units["white-lions-of-chrace"], 10)
    result = strike_unit(_piercing_swordsman(), lions)
    assert result.save_target == 5  # the printed target, before the walk's modifier
    # 1/2 to hit (WS4 vs WS4), 1/2 to wound (S3 vs T3), 5/6 failing a 6+ save
    assert result.p_unsaved == pytest.approx(0.5 * 0.5 * 5 / 6)
    assert not any("Doctored Gromril" in note for note in result.notes)


def test_unit_rule_not_in_the_walk_is_still_reported() -> None:
    """Claiming only covers what the walk factored, not every unit rule.

    Martial Prowess moves Weapon Skill in the combat's first round — a
    characteristic the walk does not own, and a round a single strike does
    not know. It stays listed, so the new claim cannot hide it.
    """
    spearmen = _fielded(REPO.units["elven-spearmen"], 10).wielding("Hand Weapon")
    lions = _fielded(REPO.units["white-lions-of-chrace"], 10)
    result = strike_unit(spearmen, lions)
    assert any("Martial Prowess" in note for note in result.notes)


def test_strike_unit_daiths_reaper_re_rolls_the_targets_successful_saves() -> None:
    """Daith's Reaper: the wielder's weapon, the target's die, the passes re-rolled.

    Spearmen given the Reaper (S+1, AP -1) strike Dwarf Warriors (T4,
    Heavy Armour): hit 4+, wound 4+, and the save worsens to 6+ — which
    must then be re-rolled, so P(save) = 1/6 * 1/6 = 1/36 and
    p_unsaved = 1/2 * 1/2 * 35/36 = 35/144. The item's rule rides the
    weapon in use, so it is claimed off the weapon-rule notes.
    """
    spearmen, dwarfs = REPO.units["elven-spearmen"], REPO.units["dwarf-warriors"]
    armed = spearmen.model_copy(update={"equipment": [*spearmen.equipment, "Daith's Reaper"]})
    target = _fielded(dwarfs, 10).wielding("Hand Weapon")

    result = strike_unit(_fielded(armed, 5).wielding("Daith's Reaper"), target)
    assert result.save_target == 6
    assert result.p_unsaved == pytest.approx(35 / 144)
    assert not any("not factored: Daith's Reaper" in note for note in result.notes)


def test_strike_unit_notes_the_targets_rules_only_its_own_blows_could_use() -> None:
    """One walk, one seat claimed: the target's offensive rules stay reported.

    Struck by spearmen, the Shadow Warriors' Ithilmar Weapons re-rolls the To
    Hit 1s of blows *they* throw — the seat of this walk nothing here resolves,
    since they do not strike back. It is reported rather than passing for
    factored. Let both sides strike and the other seat's compile claims it, so
    a fight leaves no note.
    """
    spearmen, shadows = REPO.units["elven-spearmen"], REPO.units["shadow-warriors"]
    striking = _fielded(spearmen, 5).wielding("Thrusting Spear")
    struck = _fielded(shadows, 5).wielding("Hand Weapon")

    one_sided = strike_unit(striking, struck)
    assert any(
        "not factored: Ithilmar Weapons (Shadow Warriors)" in note for note in one_sided.notes
    )

    both = fight(striking, struck)
    assert not any("Ithilmar Weapons" in note for note in both.notes)


def test_strike_unit_notes_the_strikers_save_re_roll_nothing_saves_against() -> None:
    """The mirror case: the striker's defensive rules stay reported too.

    Ironbreakers striking spearmen roll no saves — Gromril Armour re-rolls a
    die of the seat this walk gives to the spearmen — so it is reported, not
    claimed. In a fight the spearmen strike back and it is factored there.
    """
    spearmen, ironbreakers = REPO.units["elven-spearmen"], REPO.units["ironbreakers"]
    striking = _fielded(ironbreakers, 5).wielding("Hand Weapon")
    struck = _fielded(spearmen, 5).wielding("Thrusting Spear")

    one_sided = strike_unit(striking, struck)
    assert any("not factored: Gromril Armour (Ironbreakers)" in note for note in one_sided.notes)

    both = fight(striking, struck)
    assert not any("Gromril Armour" in note for note in both.notes)


def test_fight_claims_each_sides_ward_from_its_own_seat() -> None:
    """A full round reads both wards: each side's fold is in the math, never noted."""
    breakers = Contingent.deploy("ironbreakers", 10, data=REPO).wielding("Hand Weapon")
    spearmen = _fielded(REPO.units["elven-spearmen"], 10).wielding("Thrusting Spear")

    result = fight(spearmen, breakers, first_round=True)

    assert not any("Runes of Protection" in note for note in result.notes)


# --- cavalry: a ridden model fights as rider and mount, two batches ---


def _cavalry_unit(*, rider_i: int, mount_i: int) -> Unit:
    # One rider row and one mount row, both WS4 S3 A1 against a WS4 T3 foe:
    # every attack's p_unsaved is 1/2 * 1/2 = 1/4, so the goldens stay small.
    rider = {
        "name": "Rider",
        "role": "rank-and-file",
        "M": "-",
        "WS": 4,
        "BS": 4,
        "S": 3,
        "T": 3,
        "W": 1,
        "I": rider_i,
        "A": 1,
        "Ld": 8,
    }
    steed = {
        "name": "Steed",
        "role": "mount",
        "M": 8,
        "WS": 4,
        "BS": "-",
        "S": 3,
        "T": "-",
        "W": "-",
        "I": mount_i,
        "A": 1,
        "Ld": "-",
    }
    return Unit.model_validate(
        {
            "id": "riders",
            "name": "Riders",
            "points": 20,
            "unit_size": {"min": 1},
            "troop_type": "Heavy Cavalry",
            "equipment": ["Hand Weapon"],
            "profiles": [rider, steed],
        }
    ).with_troop_type(REPO.troop_types)


def _foot_unit(*, initiative: int) -> Unit:
    # A single-row foe with no armour: WS4 S3 T3 A1, on a troop type that
    # confers no rules, so the goldens carry no rule effects.
    return Unit.model_validate(
        {
            "id": "footmen",
            "name": "Footmen",
            "points": 5,
            "unit_size": {"min": 1},
            "troop_type": "War Beast",
            "equipment": ["Hand Weapon"],
            "profiles": [
                {
                    "name": "Footman",
                    "role": "rank-and-file",
                    "M": 5,
                    "WS": 4,
                    "BS": 4,
                    "S": 3,
                    "T": 3,
                    "W": 1,
                    "I": initiative,
                    "A": 1,
                    "Ld": 8,
                }
            ],
        }
    ).with_troop_type(REPO.troop_types)


def test_fight_resolves_each_batch_at_its_own_initiative() -> None:
    """Rider (I5), foe (I4), mount (I3): a model slain early loses its mount's blows.

    One model a side, every attack felling at 1/4 (4+ to hit, 4+ to wound, no
    save). Walking the Initiative steps by hand:

    - I5: the rider fells the foe with p 1/4.
    - I4: a surviving foe (3/4) fells the cavalry model with p 1/4.
    - I3: the mount attacks only while both stand (9/16), felling at 1/4 --
      a cavalry model slain at I4 never swings its mount
      (the-combat-phase/split-profiles-combat).

    Joint: P(0,1) = 1/4 + 9/64 = 25/64, P(1,0) = 12/64, P(0,0) = 27/64.
    """
    cavalry = Contingent.field(_cavalry_unit(rider_i=5, mount_i=3), 1, data=REPO).wielding(
        "Hand Weapon"
    )
    foot = Contingent.field(_foot_unit(initiative=4), 1, data=REPO).wielding("Hand Weapon")

    result = fight(cavalry, foot)

    assert result.first_striker is cavalry
    assert result.losses[0][0] == pytest.approx(27 / 64)
    assert result.losses[0][1] == pytest.approx(25 / 64)
    assert result.losses[1][0] == pytest.approx(12 / 64)
    assert result.losses[1][1] == pytest.approx(0)


def test_fight_strikes_rider_and_mount_together_at_equal_initiative() -> None:
    """Rider and mount at one Initiative strike as one step, before the slower foe.

    Both cavalry batches at I5 against a foe at I4: the foe dies before
    striking whenever either of the two attacks fells it (1 - (3/4)^2 = 7/16),
    and strikes back at 1/4 otherwise.
    """
    cavalry = Contingent.field(_cavalry_unit(rider_i=5, mount_i=5), 1, data=REPO).wielding(
        "Hand Weapon"
    )
    foot = Contingent.field(_foot_unit(initiative=4), 1, data=REPO).wielding("Hand Weapon")

    result = fight(cavalry, foot)

    assert result.losses[0][1] == pytest.approx(7 / 16)
    assert result.losses[1][0] == pytest.approx(9 / 16 * 1 / 4)
    assert result.losses[0][0] == pytest.approx(9 / 16 * 3 / 4)


def test_strike_unit_folds_the_mounts_attacks_in() -> None:
    """5 Silver Helms throw rider and steed blows alike: 4 + 4 attacks.

    The front rank is 4 wide (Heavy Cavalry); riders at WS4 and steeds at WS3
    both hit Elven Spearmen (WS4) on 4+, wound T3 on 4+ (hand weapon at S3),
    against a 5+ save: p_unsaved = 1/2 * 1/2 * 2/3 = 1/6 for all 8 attacks.
    """
    helms = Contingent.deploy("silver-helms", 5, data=REPO).wielding("Hand Weapon")
    spearmen = _fielded(REPO.units["elven-spearmen"], 20)

    result = strike_unit(helms, spearmen)

    assert result.attacks == 8
    assert result.expected_wounds == pytest.approx(8 / 6)
    assert any("mount batch folded in: 4 Barded Elven Steed attacks" in n for n in result.notes)

    # A/B: strip the steed row and the same strike throws the riders' 4 alone.
    dismounted = REPO.units["silver-helms"].model_copy(
        update={
            "profiles": [p for p in REPO.units["silver-helms"].profiles if p.role.value != "mount"]
        }
    )
    riders_only = strike_unit(
        Contingent.field(dismounted, 5, data=REPO).wielding("Hand Weapon"), spearmen
    )
    assert riders_only.attacks == 4
    assert riders_only.expected_wounds == pytest.approx(4 / 6)


def test_mount_initiative_reads_the_mount_row_plus_the_charge_bonus() -> None:
    """The mounts strike at their own printed Initiative, charge bonus included."""
    helms = Contingent.deploy("silver-helms", 5, data=REPO)
    assert mount_initiative(helms).value == 4  # the Barded Elven Steed's printed I
    assert mount_initiative(helms, 2).value == 6
    assert mount_initiative(helms, 8).value == 10  # capped, as any Initiative is

    spearmen = _fielded(REPO.units["elven-spearmen"], 5)
    with pytest.raises(ValueError, match="rides nothing"):
        mount_initiative(spearmen)


def test_a_barred_piece_is_withdrawn_whole_not_compensated() -> None:
    """The bar takes the piece with its whole bonus, whatever its size.

    A doctored tower shield improving the save by 2: light armour (6+) plus
    it saves on 4+, and a great weapon in hand withdraws both points -- a
    counter-modifier of the printed Shield's -1 would leave a phantom 5+.
    """
    from avelorn.core.registry import Registry
    from avelorn.tow.schema.armour import Armour

    tower = Armour(id="tower-shield", name="Shield", armour_value_improvement=2)
    doctored = TOWRepository()
    doctored.armoury = Registry(
        [tower if piece.id == "shield" else piece for piece in REPO.armoury.values()],
        kind="armour",
    )
    spearmen = REPO.units["elven-spearmen"]
    two_handed = spearmen.model_copy(update={"equipment": [*spearmen.equipment, "Great Weapon"]})
    towered = Contingent.field(two_handed, 10, data=doctored).wielding("Great Weapon")
    striker = Contingent.field(spearmen, 10, data=doctored).wielding("Thrusting Spear")

    at_rest = strike_unit(striker, Contingent.field(two_handed, 10, data=doctored))
    struck = strike_unit(striker, towered)

    assert at_rest.save_target == 4  # 6+ light armour bettered 2 by the tower shield
    assert struck.save_target == 6  # the whole piece withdrawn, not one point of it


def _mw_repo() -> TOWRepository:
    # The real registries plus one doctored blade printing the real rule.
    from avelorn.core.registry import Registry
    from avelorn.tow.schema.weapon import WeaponProfile

    blade = Weapon(
        id="serrated-blade",
        name="Serrated Blade",
        profiles=[
            WeaponProfile.model_validate(
                {
                    "R": "Combat",
                    "S": "S",
                    "AP": "-",
                    "special_rules": [RuleRef(rule="multiple-wounds", X=2)],
                }
            )
        ],
    )
    doctored = TOWRepository()
    doctored.weapons = Registry([*REPO.weapons.values(), blade], kind="weapon")
    return doctored


def _wounds(unit: Unit, wounds: int, *, unarmoured: bool = True) -> Unit:
    # A target of ``wounds``-Wound models, stripped to its hand weapon so the
    # per-attack chance stays the bare chart figure.
    equipment = ["Hand Weapon"] if unarmoured else unit.equipment
    doctored = unit.model_copy(
        deep=True, update={"id": f"w{wounds}", "name": f"W{wounds} Target", "equipment": equipment}
    )
    doctored.profiles[0].characteristics[Characteristic.WOUNDS] = wounds
    return doctored


def test_a_pool_mixing_plain_and_multiplied_wounds_leaves_the_rule_noted() -> None:
    """A one-sided ridden strike pools rider and mount wounds: no printed order mixes them.

    Silver Helms' riders swing the Serrated Blade while their steeds kick
    plain hooves at a W2 line — the pooled fold cannot place the multiplier
    exactly, so the math stays plain and the rule rides noted. Against W1
    models the cap levels the pool and the rule is honoured (inert) instead.
    """
    repo = _mw_repo()
    helms = REPO.units["silver-helms"]
    armed = helms.model_copy(update={"equipment": [*helms.equipment, "Serrated Blade"]})
    riders = Contingent.field(armed, 5, data=repo).wielding("Serrated Blade")
    plain = Contingent.field(helms, 5, data=repo).wielding("Hand Weapon")
    spearmen = REPO.units["elven-spearmen"]
    w2 = Contingent.field(_wounds(spearmen, 2), 10, data=repo).wielding("Hand Weapon")
    w1 = Contingent.field(_wounds(spearmen, 1), 10, data=repo).wielding("Hand Weapon")

    mixed = strike_unit(riders, w2)
    assert any(
        "weapon rule not factored: Multiple Wounds (2) (Serrated Blade)" in note
        for note in mixed.notes
    )
    assert mixed.casualties == strike_unit(plain, w2).casualties  # blade otherwise a hand weapon

    capped = strike_unit(riders, w1)
    assert not any("not factored: Multiple Wounds" in note for note in capped.notes)


def test_a_round_honours_a_multiplier_whose_batch_strikes_alone_at_its_step() -> None:
    """fight(): riders at I5 fold apart from their I4 steeds, so the multiplier lands.

    The same blade against the same W2 line, in a full round: each
    Initiative step pools only its own batches, the rider batch folds
    exactly, the rule is claimed — and the A/B numbers move.
    """
    repo = _mw_repo()
    helms = REPO.units["silver-helms"]
    armed = helms.model_copy(update={"equipment": [*helms.equipment, "Serrated Blade"]})
    riders = Contingent.field(armed, 5, data=repo).wielding("Serrated Blade")
    plain = Contingent.field(helms, 5, data=repo).wielding("Hand Weapon")
    spearmen = REPO.units["elven-spearmen"]
    target = Contingent.field(_wounds(spearmen, 2), 10, data=repo).wielding("Hand Weapon")

    mw = fight(riders, target)
    base = fight(plain, target)

    assert not any("not factored: Multiple Wounds" in note for note in mw.notes)
    assert float(expected_value(mw.b_casualties)) > float(expected_value(base.b_casualties))
