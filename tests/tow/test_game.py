"""The Game object: rules in force, phase bindings, one-line delegation."""

import dataclasses

import pytest

from avelorn.tow.combat.charge import StandAndShoot
from avelorn.tow.combat.charge import charge as charge_verb
from avelorn.tow.combat.melee import combat_result, fight
from avelorn.tow.combat.morale import break_test, make_panic_tests
from avelorn.tow.combat.shooting import shoot_unit
from avelorn.tow.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.game import TOWGame
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.stage import Stage
from avelorn.tow.schema.unit import Unit

REPO = TOWRepository()
GAME = TOWGame.assemble(REPO)


def _fielded(unit: Unit, models: int) -> Contingent:
    return GAME.field(unit, models)


def test_field_delegates_to_the_muster_boundary() -> None:
    """game.field is Contingent.field with the game's registries injected."""
    spearmen = REPO.units["elven-spearmen"]
    assert GAME.field(spearmen, 5) == Contingent.field(spearmen, 5, data=REPO)


def test_deploy_delegates_to_the_muster_boundary() -> None:
    """game.deploy is Contingent.deploy with the game's registries injected."""
    from avelorn.tow.muster import Complement

    entry = Complement(unit=REPO.units["elven-spearmen"], size=10)
    assert GAME.deploy(entry) == Contingent.field(entry, data=REPO)


def test_every_phase_category_in_data_names_a_phase() -> None:
    """A rule category that reads as a phase must be one of the turn's phases.

    Drift guard: the Phase values double as the category vocabulary, so
    a chapter rule filed under a misspelled phase would silently never
    be in force. Categories that are not phases (Special Rules) are
    other chapters, not errors.
    """
    categories = {r.category for r in REPO.rules.values() if r.category}
    phaselike = {c for c in categories if c.endswith("Phase")}
    assert phaselike <= {phase.value for phase in Phase}


def test_assemble_resolves_the_shooting_rules_in_force() -> None:
    """The shooting chapter's effectful rules are in force, resolved by name."""
    in_force = GAME.in_play[Phase.SHOOTING]
    assert set(in_force) == {"Firing at Long Range", "Moving and Shooting"}
    assert all(rule.effects for rule in in_force.values())


def test_phases_without_chapter_rules_have_none_in_force() -> None:
    """Assembly answers every phase, empty where the data has no chapter rules."""
    assert set(GAME.in_play) == set(Phase)
    assert GAME.in_play[Phase.STRATEGY] == {}


def test_the_game_is_a_frozen_value() -> None:
    """Assembled once, never mutated: the rules in force cannot be reassigned."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(GAME, "in_play", {})  # noqa: B010 — the point is the freeze


def test_turn_is_the_printed_sequence() -> None:
    """The turn walks the four phases in printed order.

    The sequence is derived from the Phase vocabulary, so a phase
    joining the enum without a matching field fails here.
    """
    assert GAME.turn() == (GAME.strategy, GAME.movement, GAME.shooting, GAME.combat)


@pytest.mark.parametrize("binding", ["strategy", "movement", "shooting", "combat"])
def test_steps_follow_the_stage_declaration_order(binding: str) -> None:
    """Each phase's printed steps keep the Stage vocabulary's order.

    Every step knows its stage; the walk derives its ordering from
    Stage declaration order, so a phase's steps must never disagree
    with it. Vacuous for phases with no steps yet — deliberately: the
    guard is already standing when they gain their first.
    """
    stages = [step.stage for step in getattr(GAME, binding).steps]
    assert stages == [stage for stage in Stage if stage in set(stages)]


def test_volley_delegates_to_shoot_unit() -> None:
    """game.shooting.volley is shoot_unit with the game's rules injected."""
    archers = _fielded(REPO.units["elven-archers"], 3)
    spearmen = _fielded(REPO.units["elven-spearmen"], 10)
    longbow = REPO.weapons["longbow"]
    bound = GAME.shooting.volley(archers, spearmen, longbow, distance=20)
    direct = shoot_unit(
        archers, spearmen, longbow, phase_rules=GAME.in_play[Phase.SHOOTING], distance=20
    )
    assert bound == direct


def test_make_panic_tests_delegates() -> None:
    """game.shooting.make_panic_tests is the morale seam, bound."""
    archers = _fielded(REPO.units["elven-archers"], 3)
    spearmen = _fielded(REPO.units["elven-spearmen"], 10)
    volley = GAME.shooting.volley(archers, spearmen, REPO.weapons["longbow"])
    assert GAME.shooting.make_panic_tests(volley, spearmen) == make_panic_tests(volley, spearmen)


def test_fight_result_and_break_test_delegate() -> None:
    """The combat binding's three actions match the module functions."""
    spearmen = REPO.units["elven-spearmen"]
    a, b = _fielded(spearmen, 5), _fielded(spearmen, 5)
    spear = REPO.weapons["thrusting-spear"]
    bound = GAME.combat.fight(a, b, a_weapon=spear, b_weapon=spear, first_round=True)
    direct = fight(
        a,
        b,
        a_weapon=spear,
        b_weapon=spear,
        first_round=True,
        phase_rules=GAME.in_play[Phase.COMBAT],
    )
    assert bound == direct
    scored = GAME.combat.result(bound)
    assert scored == combat_result(direct)
    assert GAME.combat.break_test(scored, spearmen, spearmen) == break_test(
        scored, spearmen, spearmen
    )


def test_the_charge_is_a_movement_action() -> None:
    """game.movement.charge is the charge sequence, rules in force injected."""
    spearmen = _fielded(REPO.units["elven-spearmen"], 5)
    archers = _fielded(REPO.units["elven-archers"], 5)
    move = Charge(3, ChargeArc.FRONT)
    bound = GAME.movement.charge(
        spearmen,
        archers,
        move=move,
        charger_weapon=REPO.weapons["thrusting-spear"],
        target_weapon=REPO.weapons["hand-weapon"],
        reaction=StandAndShoot(REPO.weapons["longbow"]),
    )
    direct = charge_verb(
        spearmen,
        archers,
        move=move,
        charger_weapon=REPO.weapons["thrusting-spear"],
        target_weapon=REPO.weapons["hand-weapon"],
        reaction=StandAndShoot(REPO.weapons["longbow"]),
        phase_rules=GAME.in_play[Phase.SHOOTING],
    )
    assert bound == direct


def test_each_phase_declares_the_dice_the_engine_rolls() -> None:
    """The phase's steps are the declaration; the attack factory answers to it.

    Drift guard: an attack built for a phase must roll exactly the
    attack dice its steps declare, in printed order. Steps that are no
    attack roll (the panic test's unit-wide 2D6) sit in the same tuple,
    each knowing what it rolls.
    """
    from avelorn.tow.combat.attack import AttackProfile, AttackRoll

    shot = AttackProfile.shooting(hit_target=4, wound_target=4, save_target=4, ward_target=4)
    blow = AttackProfile.melee(hit_target=4, wound_target=4, save_target=4, ward_target=4)
    attack_steps = tuple(s for s in GAME.shooting.steps if issubclass(s, AttackRoll))
    assert tuple(type(roll) for roll in shot.rolls) == attack_steps
    attack_steps = tuple(s for s in GAME.combat.steps if issubclass(s, AttackRoll))
    assert tuple(type(roll) for roll in blow.rolls) == attack_steps
