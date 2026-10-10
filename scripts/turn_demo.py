"""Did you know you can walk the printed turn, phase by phase?

One player-turn through the context-manager surface: a charge in the Movement
phase locks the units in combat, so the Shooting phase has nothing to shoot,
and the Combat phase fights the engagement the charge formed.
"""

from fractions import Fraction

from avelorn.core.distribution import Distribution
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot
from avelorn.tow.steps import Fought


def main() -> None:
    """Walk one turn: Spearmen charge Archers, who Stand & Shoot, then fight."""
    game = TOWGame.load_data()
    spearmen = game.field(game.units["elven-spearmen"], 20).wielding("Thrusting Spear")
    archers = game.field(game.units["elven-archers"], 10).wielding("Hand Weapon")

    turn = game.turn()
    with turn.movement() as movement:
        engagement = movement.charge(spearmen, archers, Charge(8, ChargeArc.FRONT))
        volley = engagement.react(StandAndShoot())
    with turn.shooting():
        pass  # both units are now locked in combat — nothing to shoot
    with turn.combat() as combat:
        fought = combat.fight(engagement).fought.mass
    won, drawn, lost = (fought.get(each, 0) for each in (Fought.WON, Fought.DRAWN, Fought.LOST))

    toll = volley.casualties if volley else Distribution.pure(0)
    print('Walking one turn -- 20 Spearmen charge 10 Archers (8"):')
    print(f"  Movement: Archers Stand & Shoot, {toll.expect(Fraction):.2f} chargers felled.")
    print("  Shooting: both locked in combat -- no shots.")
    print(f"  Combat:   P(Spearmen win) {won:.3f}  draw {drawn:.3f}  P(Archers win) {lost:.3f}")
    # Exact, so this is an identity rather than a rounding: the three outcomes of
    # a scored round account for all of it.
    print(f"  ... those three sum to {won + drawn + lost} exactly.")


if __name__ == "__main__":
    main()
