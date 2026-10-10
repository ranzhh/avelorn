"""The Game object: rules in force, phase bindings, one-line delegation."""

import dataclasses
from fractions import Fraction

import pytest

from avelorn.tow.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.side import Side
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


def test_the_game_is_a_frozen_value() -> None:
    """Assembled once, never mutated: its phases cannot be reassigned."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(GAME, "combat", GAME.combat)  # noqa: B010


def test_phases_are_the_printed_sequence() -> None:
    """game.phases() lists the four phases in printed order.

    The sequence is derived from the Phase vocabulary, so a phase
    joining the enum without a matching field fails here.
    """
    assert GAME.phases() == (GAME.strategy, GAME.movement, GAME.shooting, GAME.combat)


def test_a_volley_runs_on_the_program_with_the_corpus_rules() -> None:
    """Archers at long range shoot under Firing at Long Range.

    They hit on 4+ and wound on 4+, and a natural 6 To Wound worsens the
    Spearmen's 5+ save to 6+ by the longbow's Armour Bane (1):
    1/2 * (2/6 * 2/3 + 1/6 * 5/6) = 13/72 a shot.
    """
    archers = _fielded(REPO.units["elven-archers"], 3).wielding("Longbow")
    spearmen = _fielded(REPO.units["elven-spearmen"], 10)

    fired = GAME.shooting.volley(archers, spearmen, distance=20)

    assert fired.applied("volley/attacker/attack/elven-archer/roll-to-hit") == (
        "Firing at Long Range",
    )
    assert fired.p_unsaved == Fraction(13, 72)


def test_a_round_runs_on_the_program_with_the_corpus_rules() -> None:
    """Spearmen fight Spearmen at once.

    Neither charged, so it is no first round, and both strike at Initiative 4.
    """
    spearmen = REPO.units["elven-spearmen"]
    a = _fielded(spearmen, 5).wielding("Thrusting Spear")
    b = _fielded(spearmen, 5).wielding("Thrusting Spear")

    fought = GAME.combat.fight(a, b)

    assert fought.first_striker is None
    assert (fought.initiative(Side.ATTACKER), fought.initiative(Side.TARGET)) == (4, 4)


def test_a_charge_reaction_runs_on_the_program_with_the_corpus_rules() -> None:
    """Archers stand and shoot at the Spearmen charging them, under Standing and Shooting."""
    spearmen = _fielded(REPO.units["elven-spearmen"], 5)
    archers = _fielded(REPO.units["elven-archers"], 5)

    engagement = GAME.movement.charge(spearmen, archers, Charge(3, ChargeArc.FRONT))
    fired = engagement.react(StandAndShoot("Longbow"))

    assert fired is not None
    assert fired.applied("stand-and-shoot/attacker/attack/elven-archer/roll-to-hit") == (
        "Standing and Shooting",
    )
