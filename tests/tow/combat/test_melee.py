"""Close-combat strike tests, golden values hand-computed from the charts."""

import pytest

from avelorn.core.dice import binomial_distribution, expected_value
from avelorn.tow.combat.context import CombatContext
from avelorn.tow.combat.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.combat.melee import (
    combat_result,
    effective_initiative,
    fight,
    strike,
    strike_unit,
)
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.unit import Characteristic, Unit

REPO = TOWRepository()


def _fielded(unit: Unit, models: int) -> Contingent:
    # Field at the printed, optionless loadout, with the real registries.
    return Contingent.field(
        unit, models, weapons=REPO.weapons, armoury=REPO.armoury, rules=REPO.rules
    )


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
        _fielded(spearmen, 5),
        _fielded(spearmen, 10),
        REPO.weapons["thrusting-spear"],
        armoury=REPO.armoury,
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
    spearmen = REPO.units["elven-spearmen"]
    two_attacks = spearmen.model_copy(deep=True)
    two_attacks.profiles[0].characteristics[Characteristic.ATTACKS] = 2
    result = strike_unit(
        _fielded(two_attacks, 5),
        _fielded(spearmen, 10),
        REPO.weapons["thrusting-spear"],
        armoury=REPO.armoury,
    )
    assert result.attacks == 10


def test_strike_unit_without_armoury_degrades_visibly() -> None:
    """No armoury: the defender's armour is unresolved and reported, not guessed."""
    spearmen = REPO.units["elven-spearmen"]
    result = strike_unit(
        _fielded(spearmen, 5), _fielded(spearmen, 10), REPO.weapons["thrusting-spear"]
    )
    assert result.save_target is None
    assert any("Light Armour" in note for note in result.notes)


def test_strike_unit_rejects_a_missile_only_weapon() -> None:
    """A weapon with no Combat profile cannot be used to fight."""
    archers = REPO.units["elven-archers"]
    with pytest.raises(ValueError, match="no Combat profile"):
        strike_unit(_fielded(archers, 5), _fielded(archers, 10), REPO.weapons["longbow"])


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
    spear = REPO.weapons["thrusting-spear"]
    side = _fielded(spearmen, 1)
    result = fight(side, side, a_weapon=spear, b_weapon=spear, armoury=REPO.armoury)
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
    spear = REPO.weapons["thrusting-spear"]
    faster = _fielded(_higher_initiative(spearmen), 1)
    slower = _fielded(spearmen, 1)
    result = fight(faster, slower, a_weapon=spear, b_weapon=spear, armoury=REPO.armoury)
    assert result.first_striker is faster
    assert result.b_casualties[1] == pytest.approx(1 / 6)  # A full-strength
    assert result.a_casualties[1] == pytest.approx(5 / 36)  # B struck back reduced


def test_fight_orients_the_joint_to_the_arguments() -> None:
    """When the second argument strikes first, losses stay keyed to (a, b)."""
    spearmen = REPO.units["elven-spearmen"]
    spear = REPO.weapons["thrusting-spear"]
    slower = _fielded(spearmen, 1)
    faster = _fielded(_higher_initiative(spearmen), 1)
    result = fight(slower, faster, a_weapon=spear, b_weapon=spear, armoury=REPO.armoury)
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
    spear = REPO.weapons["thrusting-spear"]
    result = fight(
        _fielded(_higher_initiative(spearmen), 5),
        _fielded(spearmen, 5),
        a_weapon=spear,
        b_weapon=spear,
        armoury=REPO.armoury,
    )
    full_strength = strike_unit(
        _fielded(spearmen, 5), _fielded(spearmen, 5), spear, armoury=REPO.armoury
    )
    assert expected_value(result.a_casualties) < expected_value(full_strength.casualties)
    assert any("Fight In Extra Rank" in note for note in result.notes)


def test_fight_rejects_negative_models() -> None:
    """A negative model count is a programming error, not a silent zero."""
    spearmen = REPO.units["elven-spearmen"]
    spear = REPO.weapons["thrusting-spear"]
    with pytest.raises(ValueError, match="model counts must be >= 0"):
        fight(
            _fielded(spearmen, -1),
            _fielded(spearmen, 5),
            a_weapon=spear,
            b_weapon=spear,
            armoury=REPO.armoury,
        )


# --- fight(): pre-combat losses folded in (a_prior_losses / b_prior_losses) ---


def test_fight_degenerate_prior_losses_equal_a_plain_fight() -> None:
    """A pmf certain no models were lost reproduces the plain-fight joint."""
    spearmen = REPO.units["elven-spearmen"]
    spear = REPO.weapons["thrusting-spear"]
    a, b = _fielded(spearmen, 3), _fielded(spearmen, 3)
    plain = fight(a, b, a_weapon=spear, b_weapon=spear, armoury=REPO.armoury)
    with_prior = fight(
        a, b, a_weapon=spear, b_weapon=spear, a_prior_losses=[1.0], armoury=REPO.armoury
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
    spear = REPO.weapons["thrusting-spear"]
    a, b = _fielded(spearmen, 1), _fielded(spearmen, 1)
    result = fight(
        a, b, a_weapon=spear, b_weapon=spear, a_prior_losses=[0.5, 0.5], armoury=REPO.armoury
    )
    assert result.a_casualties[1] == pytest.approx(0.5 * 1 / 6)  # only the full branch
    assert result.b_casualties[1] == pytest.approx(0.5 * 1 / 6)
    assert sum(sum(row) for row in result.losses) == pytest.approx(1.0)


def test_fight_prior_losses_reject_more_losses_than_models() -> None:
    """A pmf longer than the side's models + 1 cannot describe its losses."""
    spearmen = REPO.units["elven-spearmen"]
    spear = REPO.weapons["thrusting-spear"]
    a, b = _fielded(spearmen, 2), _fielded(spearmen, 2)
    with pytest.raises(ValueError, match="a_prior_losses covers more losses"):
        fight(a, b, a_weapon=spear, b_weapon=spear, a_prior_losses=[0.25, 0.25, 0.25, 0.25])


def test_fight_prior_losses_reject_a_non_distribution() -> None:
    """A prior-loss pmf that is not a probability distribution is rejected."""
    spearmen = REPO.units["elven-spearmen"]
    spear = REPO.weapons["thrusting-spear"]
    a, b = _fielded(spearmen, 2), _fielded(spearmen, 2)
    with pytest.raises(ValueError, match="must sum to 1"):
        fight(a, b, a_weapon=spear, b_weapon=spear, b_prior_losses=[0.5, 0.2])


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
    assert effective_initiative(charger, Charge(inches, arc)) == expected


def test_effective_initiative_caps_at_ten() -> None:
    """The charge bonus cannot lift Initiative past the printed cap of 10."""
    fast = _higher_initiative(REPO.units["elven-spearmen"], 9)
    charger = _fielded(fast, 5)
    assert effective_initiative(charger, Charge(5, ChargeArc.FLANK)) == 10  # 9 + 4 -> 10


def test_fight_charge_makes_the_charger_strike_first() -> None:
    """A charge flips an equal-Initiative combat: the charger swings first.

    Both units are I4, so a standing fight is simultaneous; a 3" charge lifts
    the charger to I7, so it strikes first and its foe swings back reduced.
    """
    spearmen = REPO.units["elven-spearmen"]
    spear = REPO.weapons["thrusting-spear"]
    charger = _fielded(spearmen, 1)
    defender = _fielded(spearmen, 1)
    result = fight(
        charger,
        defender,
        a_weapon=spear,
        b_weapon=spear,
        context=CombatContext(a_charge=Charge(3, ChargeArc.FRONT)),
        armoury=REPO.armoury,
    )
    assert result.first_striker is charger
    assert result.b_casualties[1] == pytest.approx(1 / 6)  # charger struck full-strength
    assert result.a_casualties[1] == pytest.approx(5 / 36)  # defender struck back reduced


def test_fight_charge_capped_below_the_foe_stays_simultaneous() -> None:
    """A charge whose bonus does not exceed the foe's Initiative changes no order.

    A 0" charge grants +0, so two I4 units still strike simultaneously — the
    bonus must actually raise Initiative above the foe's to matter.
    """
    spearmen = REPO.units["elven-spearmen"]
    spear = REPO.weapons["thrusting-spear"]
    charger = _fielded(spearmen, 1)
    result = fight(
        charger,
        _fielded(spearmen, 1),
        a_weapon=spear,
        b_weapon=spear,
        context=CombatContext(a_charge=Charge(0, ChargeArc.FRONT)),
        armoury=REPO.armoury,
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
    spear = REPO.weapons["thrusting-spear"]
    result = fight(
        _fielded(_higher_initiative(spearmen), 1),
        _fielded(spearmen, 1),
        a_weapon=spear,
        b_weapon=spear,
        armoury=REPO.armoury,
    )
    cr = combat_result(result)
    assert cr.p_a_wins == pytest.approx(1 / 6)
    assert cr.p_b_wins == pytest.approx(5 / 36)
    assert cr.p_draw == pytest.approx(25 / 36)
    assert cr.margin[1] == pytest.approx(6 / 36)  # A ahead by one wound
    assert cr.margin[-1] == pytest.approx(5 / 36)  # B ahead by one wound
    assert sum(cr.margin.values()) == pytest.approx(1.0)
    assert any("rank bonus" in note for note in cr.notes)


def test_combat_result_simultaneous_is_symmetric() -> None:
    """Equal Initiative: the win split is symmetric between the two sides."""
    spearmen = REPO.units["elven-spearmen"]
    spear = REPO.weapons["thrusting-spear"]
    side = _fielded(spearmen, 1)
    cr = combat_result(fight(side, side, a_weapon=spear, b_weapon=spear, armoury=REPO.armoury))
    assert cr.p_a_wins == pytest.approx(cr.p_b_wins)
    assert cr.p_a_wins == pytest.approx(5 / 36)
    assert cr.p_draw == pytest.approx(26 / 36)
