"""Walking a turn: its phase order and the engagements it tracks."""

import pytest

from avelorn.tow.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot

REPO = TOWRepository()
GAME = TOWGame.assemble(REPO)


def _spearmen(models: int) -> Contingent:
    return Contingent.field(REPO.units["elven-spearmen"], models, data=REPO)


def _archers(models: int) -> Contingent:
    return Contingent.field(REPO.units["elven-archers"], models, data=REPO)


def test_a_charge_in_movement_is_fought_in_combat() -> None:
    """The engagement a charge forms is carried to the Combat phase and fought.

    The charger strikes first, and its Stand & Shoot reaction thinned it before
    the melee.
    """
    turn = GAME.turn()
    with turn.movement() as mv:
        engagement = mv.charge(_spearmen(10), _archers(10), Charge(8, ChargeArc.FRONT))
        engagement.react(StandAndShoot(REPO.weapons["longbow"]))
    with turn.combat() as cb:
        fought = cb.fight(
            engagement,
            a_weapon=REPO.weapons["thrusting-spear"],
            b_weapon=REPO.weapons["hand-weapon"],
        )
    assert fought.first_striker is engagement.a  # the charger struck first
    assert engagement.reaction is not None  # the Stand & Shoot volley was resolved


def test_a_phase_cannot_be_taken_out_of_order() -> None:
    """Entering an earlier phase after a later one is refused."""
    turn = GAME.turn()
    with turn.combat():
        pass
    with pytest.raises(ValueError, match="cannot be entered after"):  # noqa: SIM117 — the raise is the point
        with turn.movement():
            pass


def test_a_phase_cannot_be_re_entered() -> None:
    """A phase is walked once; re-entering it is refused."""
    turn = GAME.turn()
    with turn.movement():
        pass
    with pytest.raises(ValueError, match="cannot be entered after"):  # noqa: SIM117 — the raise is the point
        with turn.movement():
            pass


def test_phases_may_be_skipped_forward() -> None:
    """A phase with nothing to do may be skipped: Strategy then Combat is fine."""
    turn = GAME.turn()
    with turn.strategy():
        pass
    with turn.combat():  # movement and shooting skipped, no error
        pass
