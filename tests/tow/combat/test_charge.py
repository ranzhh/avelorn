"""The charge sequence: the verb, its reactions, and the composed fight."""

from dataclasses import replace

import pytest

from avelorn.tow.combat.charge import StandAndShoot, charge, stand_and_shoot
from avelorn.tow.combat.context import CombatContext
from avelorn.tow.combat.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.combat.melee import combat_result, fight
from avelorn.tow.combat.shooting import shoot_unit
from avelorn.tow.data import TOWRepository
from avelorn.tow.game import TOWGame
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.unit import Unit

REPO = TOWRepository()

# The shooting phase's rules in force, as the Game assembles them.
IN_FORCE = TOWGame.assemble(REPO.rules).in_play[Phase.SHOOTING]


def _fielded(unit: Unit, models: int) -> Contingent:
    # Field at the printed, optionless loadout, with the real registries.
    return Contingent.field(
        unit, models, weapons=REPO.weapons, armoury=REPO.armoury, rules=REPO.rules
    )


def test_stand_and_shoot_applies_the_minus_one_to_hit() -> None:
    """Archers standing and shooting hit at -1: BS4 (3+) becomes 4+."""
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    plain = shoot_unit(
        _fielded(archers, 10),
        _fielded(spearmen, 10),
        REPO.weapons["longbow"],
        phase_rules=IN_FORCE,
    )
    reaction = stand_and_shoot(
        _fielded(archers, 10),
        _fielded(spearmen, 10),
        REPO.weapons["longbow"],
        phase_rules=IN_FORCE,
    )
    assert plain.hit_target == 3
    assert reaction.hit_target == 4  # -1 To Hit for Standing and Shooting


def test_stand_and_shoot_is_exempt_from_firing_at_long_range() -> None:
    """The reaction never carries a Firing at Long Range note: the rule is a no-op.

    A plain volley with no distance leaves the range band unknown, so the
    rule is reported unfactored; the reaction asserts the exemption, so it
    is honoured silently instead.
    """
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    plain = shoot_unit(
        _fielded(archers, 10),
        _fielded(spearmen, 10),
        REPO.weapons["longbow"],
        phase_rules=IN_FORCE,
    )
    reaction = stand_and_shoot(
        _fielded(archers, 10),
        _fielded(spearmen, 10),
        REPO.weapons["longbow"],
        phase_rules=IN_FORCE,
    )
    assert any("Firing at Long Range" in note for note in plain.notes)
    assert not any("Firing at Long Range" in note for note in reaction.notes)


def test_stand_and_shoot_caps_casualties_at_the_charging_unit_size() -> None:
    """A volley cannot fell more chargers than the charging unit contains."""
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    reaction = stand_and_shoot(
        _fielded(archers, 20),
        _fielded(spearmen, 5),
        REPO.weapons["longbow"],
        phase_rules=IN_FORCE,
    )
    assert reaction.target_models == 5
    assert len(reaction.casualties) == 6  # 0..5
    assert sum(reaction.casualties) == pytest.approx(1.0)


# --- The whole sequence: Stand & Shoot feeding the composed melee ---


def test_charge_sequence_matches_mixing_the_survivor_fights_by_hand() -> None:
    """fight() over the reaction pmf equals summing P(k) x the N-k survivor fight.

    The Archers Stand & Shoot the charging Spearmen; feeding that casualty
    pmf to fight() as ``a_prior_losses`` must reproduce, exactly, a by-hand
    mixture over each number ``k`` of Spearmen felled before contact.
    """
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    spear, hand = REPO.weapons["thrusting-spear"], REPO.weapons["hand-weapon"]
    move = Charge(6, ChargeArc.FRONT)
    models = 3
    charger = _fielded(spearmen, models)
    defender = _fielded(archers, 3)
    reaction = stand_and_shoot(defender, charger, REPO.weapons["longbow"], phase_rules=IN_FORCE)

    composed = fight(
        charger,
        defender,
        a_weapon=spear,
        b_weapon=hand,
        a_prior_losses=reaction.casualties,
        context=CombatContext(a_charge=move),
    )

    manual = [[0.0] * (defender.models + 1) for _ in range(models + 1)]
    for felled, p_felled in enumerate(reaction.casualties):
        survivors = fight(
            replace(charger, models=models - felled),
            defender,
            a_weapon=spear,
            b_weapon=hand,
            context=CombatContext(a_charge=move),
        )
        for a_lost, row in enumerate(survivors.losses):
            for b_lost, mass in enumerate(row):
                manual[a_lost][b_lost] += p_felled * mass

    for composed_row, manual_row in zip(composed.losses, manual, strict=True):
        assert composed_row == pytest.approx(manual_row)
    assert composed.first_striker is charger  # the charge still strikes first


def test_stand_and_shoot_erodes_the_chargers_combat_result() -> None:
    """Softening the chargers first lowers their combat-result win chance.

    A charge met by Stand & Shoot brings fewer Spearmen to the melee, so
    they inflict fewer wounds and win the combat less often than an un-shot
    charge of the same size would.
    """
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    spear, hand = REPO.weapons["thrusting-spear"], REPO.weapons["hand-weapon"]
    charger = _fielded(spearmen, 10)
    defender = _fielded(archers, 10)
    situation = CombatContext(a_charge=Charge(8, ChargeArc.FRONT))
    reaction = stand_and_shoot(defender, charger, REPO.weapons["longbow"], phase_rules=IN_FORCE)

    unshot = combat_result(
        fight(
            charger,
            defender,
            a_weapon=spear,
            b_weapon=hand,
            context=situation,
        )
    )
    shot = combat_result(
        fight(
            charger,
            defender,
            a_weapon=spear,
            b_weapon=hand,
            a_prior_losses=reaction.casualties,
            context=situation,
        )
    )
    assert shot.p_a_wins < unshot.p_a_wins


def test_force_short_range_honours_long_range_as_a_no_op() -> None:
    """shoot_unit's force_short_range treats the shot as within half range."""
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    forced = shoot_unit(
        _fielded(archers, 10),
        _fielded(spearmen, 10),
        REPO.weapons["longbow"],
        phase_rules=IN_FORCE,
        force_short_range=True,
    )
    assert not any("Firing at Long Range" in note for note in forced.notes)


# --- charge(): the verb composing reaction and fight ---


def test_charge_composes_the_reaction_into_the_fight() -> None:
    """charge() equals stand_and_shoot and fight composed by hand."""
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    spear, hand = REPO.weapons["thrusting-spear"], REPO.weapons["hand-weapon"]
    longbow = REPO.weapons["longbow"]
    charger, target = _fielded(spearmen, 10), _fielded(archers, 10)
    move = Charge(8, ChargeArc.FRONT)

    outcome = charge(
        charger,
        target,
        move=move,
        charger_weapon=spear,
        target_weapon=hand,
        reaction=StandAndShoot(longbow),
        phase_rules=IN_FORCE,
    )

    volley = stand_and_shoot(target, charger, longbow, phase_rules=IN_FORCE)
    manual = fight(
        charger,
        target,
        a_weapon=spear,
        b_weapon=hand,
        a_prior_losses=volley.casualties,
        context=CombatContext(a_charge=move),
    )
    assert outcome.reaction == volley
    assert outcome.melee.losses == manual.losses
    assert outcome.melee.first_striker is charger  # the move raised the charger's Initiative


def test_charge_against_a_holding_target_has_no_volley() -> None:
    """Hold: no reaction volley, and the melee is the plain charged fight."""
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    spear, hand = REPO.weapons["thrusting-spear"], REPO.weapons["hand-weapon"]
    charger, target = _fielded(spearmen, 10), _fielded(archers, 10)
    move = Charge(8, ChargeArc.FRONT)

    outcome = charge(
        charger,
        target,
        move=move,
        charger_weapon=spear,
        target_weapon=hand,
        phase_rules=IN_FORCE,
    )

    manual = fight(
        charger,
        target,
        a_weapon=spear,
        b_weapon=hand,
        context=CombatContext(a_charge=move),
    )
    assert outcome.reaction is None
    assert outcome.melee.losses == manual.losses
