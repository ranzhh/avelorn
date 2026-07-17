"""The Movement phase: the charge, its reactions, and the engagement it forms."""

import pytest

from avelorn.core.errors import UnmodelledRuleError
from avelorn.tow.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.phases.combat import CombatPhase, combat_result, fight
from avelorn.tow.phases.movement import Flee, StandAndShoot, charge, stand_and_shoot
from avelorn.tow.phases.shooting import shoot_unit
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.unit import Unit

REPO = TOWRepository()

# The shooting chapter's rules in force, built directly: these tests
# exercise the combat layer, which must not depend on game assembly.
IN_FORCE = {r.name: r for r in REPO.rules.values() if r.category == Phase.SHOOTING and r.effects}

# The Combat phase with no chapter rules in force, for fighting an engagement
# these Movement-phase tests have formed.
COMBAT = CombatPhase(in_play={})


def _fielded(unit: Unit, models: int) -> Contingent:
    # Field at the printed, optionless loadout, with the real registries.
    return Contingent.field(unit, models, data=REPO)


def test_stand_and_shoot_applies_the_minus_one_to_hit() -> None:
    """Archers standing and shooting hit at -1: BS4 (3+) becomes 4+."""
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    plain = shoot_unit(
        _fielded(archers, 10).wielding("Longbow"),
        _fielded(spearmen, 10),
        phase_rules=IN_FORCE,
    )
    reaction = stand_and_shoot(
        _fielded(archers, 10).wielding("Longbow"),
        _fielded(spearmen, 10),
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
        _fielded(archers, 10).wielding("Longbow"),
        _fielded(spearmen, 10),
        phase_rules=IN_FORCE,
    )
    reaction = stand_and_shoot(
        _fielded(archers, 10).wielding("Longbow"),
        _fielded(spearmen, 10),
        phase_rules=IN_FORCE,
    )
    assert any("Firing at Long Range" in note for note in plain.notes)
    assert not any("Firing at Long Range" in note for note in reaction.notes)


def test_stand_and_shoot_caps_casualties_at_the_charging_unit_size() -> None:
    """A volley cannot fell more chargers than the charging unit contains."""
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    reaction = stand_and_shoot(
        _fielded(archers, 20).wielding("Longbow"),
        _fielded(spearmen, 5),
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
    move = Charge(6, ChargeArc.FRONT)
    models = 3
    charger = _fielded(spearmen, models).wielding("Thrusting Spear").charging(move)
    defender = _fielded(archers, 3).wielding("Hand Weapon")
    reaction = stand_and_shoot(defender.wielding("Longbow"), charger, phase_rules=IN_FORCE)

    composed = fight(
        charger,
        defender,
        a_prior_losses=reaction.casualties,
    )

    manual = [[0.0] * (defender.models + 1) for _ in range(models + 1)]
    for felled, p_felled in enumerate(reaction.casualties):
        survivors = fight(
            charger.remove_casualties(felled),
            defender,
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
    charger = (
        _fielded(spearmen, 10).wielding("Thrusting Spear").charging(Charge(8, ChargeArc.FRONT))
    )
    defender = _fielded(archers, 10).wielding("Hand Weapon")
    reaction = stand_and_shoot(defender.wielding("Longbow"), charger, phase_rules=IN_FORCE)

    unshot = combat_result(
        fight(
            charger,
            defender,
        )
    )
    shot = combat_result(
        fight(
            charger,
            defender,
            a_prior_losses=reaction.casualties,
        )
    )
    assert shot.p_a_wins < unshot.p_a_wins


def test_force_short_range_honours_long_range_as_a_no_op() -> None:
    """shoot_unit's force_short_range treats the shot as within half range."""
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    forced = shoot_unit(
        _fielded(archers, 10).wielding("Longbow"),
        _fielded(spearmen, 10),
        phase_rules=IN_FORCE,
        force_short_range=True,
    )
    assert not any("Firing at Long Range" in note for note in forced.notes)


# --- charge(): the Movement-phase charge, its reaction, and the engagement ---


def test_charge_forms_an_engagement_and_its_reaction() -> None:
    """charge() forms an engagement; react() resolves the Stand & Shoot volley.

    The charge is a Movement-phase event only: it locks the units in combat
    (the charger entering carrying its charge) and the target's reaction
    volley matches resolving stand_and_shoot by hand. No melee is fought here.
    """
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    charger, target = _fielded(spearmen, 10), _fielded(archers, 10)
    move = Charge(8, ChargeArc.FRONT)

    engagement = charge(charger, target, move, shooting_rules=IN_FORCE)
    volley = engagement.react(StandAndShoot("Longbow"))

    assert engagement.a.movement.charge == move  # the charger entered carrying the charge
    assert engagement.b is target
    assert volley == stand_and_shoot(target.wielding("Longbow"), charger, phase_rules=IN_FORCE)
    assert engagement.reaction is volley


def test_stand_and_shoot_defaults_to_the_sole_missile_weapon() -> None:
    """StandAndShoot() with no weapon fires the reacting unit's only missile weapon.

    The target holds a Hand Weapon for the ensuing melee, but the reaction
    ignores that arm and fires its sole bow — the same volley as naming it.
    """
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    charger = _fielded(spearmen, 10).wielding("Thrusting Spear")
    target = _fielded(archers, 10).wielding("Hand Weapon")
    move = Charge(8, ChargeArc.FRONT)

    named = charge(charger, target, move, shooting_rules=IN_FORCE).react(StandAndShoot("Longbow"))
    default = charge(charger, target, move, shooting_rules=IN_FORCE).react(StandAndShoot())
    assert default == named


def test_fighting_the_engagement_is_the_charges_first_round() -> None:
    """The Combat-phase fight of an engagement equals fight() composed by hand.

    The combat-phase fight enters the chargers thinned by the reaction and
    marks the combat's first round; the charger struck first.
    """
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    charger = _fielded(spearmen, 10).wielding("Thrusting Spear")
    target = _fielded(archers, 10).wielding("Hand Weapon")
    move = Charge(8, ChargeArc.FRONT)

    engagement = charge(charger, target, move, shooting_rules=IN_FORCE)
    volley = engagement.react(StandAndShoot("Longbow"))
    assert volley is not None  # a Stand & Shoot reaction always looses a volley
    outcome = COMBAT.fight(engagement)

    manual = fight(
        charger.charging(move),
        target,
        a_prior_losses=volley.casualties,
        first_round=True,
    )
    assert outcome.losses == manual.losses
    assert outcome.first_striker is not None
    assert outcome.first_striker.movement.charge == move  # the charger struck first


def test_a_held_charge_fights_with_no_prior_losses() -> None:
    """Hold: no reaction volley, and the engagement's fight is the plain charge."""
    archers, spearmen = REPO.units["elven-archers"], REPO.units["elven-spearmen"]
    charger = _fielded(spearmen, 10).wielding("Thrusting Spear")
    target = _fielded(archers, 10).wielding("Hand Weapon")
    move = Charge(8, ChargeArc.FRONT)

    engagement = charge(charger, target, move, shooting_rules=IN_FORCE)
    engagement.react()  # default: Hold
    outcome = COMBAT.fight(engagement)

    manual = fight(charger.charging(move), target, first_round=True)
    assert engagement.reaction is None
    assert outcome.losses == manual.losses


def test_the_reaction_vocabulary_is_the_printed_three() -> None:
    """Hold is the default and takes no volley; Flee is a loud error.

    "There are three charge reactions available to the inactive player:
    Hold, Stand & Shoot and Flee" (the-movement-phase/charge-reactions).
    Flee is in the vocabulary but not modelled, and refusing loudly
    beats resolving a charge whose target silently stood still.
    """
    charger = _fielded(REPO.units["elven-spearmen"], 5)
    target = _fielded(REPO.units["elven-archers"], 5)
    move = Charge(3, ChargeArc.FRONT)

    held = charge(charger, target, move, shooting_rules=IN_FORCE)
    assert held.react() is None  # Hold: the default, no volley
    with pytest.raises(UnmodelledRuleError, match="Flee"):
        charge(charger, target, move, shooting_rules=IN_FORCE).react(Flee())


def test_end_turn_ages_the_engagement_out_of_its_first_round() -> None:
    """A charge forms a first-round engagement; end_turn clears the flag.

    The combat persists, so next turn it is no longer the charge's first
    round — the charge bonus and first-round rules lapse.
    """
    charger = _fielded(REPO.units["elven-spearmen"], 5)
    target = _fielded(REPO.units["elven-archers"], 5)
    engagement = charge(charger, target, Charge(3, ChargeArc.FRONT), shooting_rules=IN_FORCE)
    assert engagement.first_round is True
    engagement.end_turn()
    assert engagement.first_round is False
