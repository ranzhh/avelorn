"""Did you know you can walk the printed turn, phase by phase?

One player-turn through the context-manager surface: a charge in the Movement
phase locks the units in combat, so the Shooting phase has nothing to shoot,
and the Combat phase fights the engagement the charge formed.
"""

from avelorn.core.distribution import Distribution
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot


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
        scored = combat.result(combat.fight(engagement))

    felled = Distribution.from_counts(volley.casualties).expect(float) if volley else 0.0
    print('Walking one turn — 20 Spearmen charge 10 Archers (8"):')
    print(f"  Movement: Archers Stand & Shoot, {felled:.2f} chargers felled.")
    print("  Shooting: both locked in combat — no shots.")
    print(
        f"  Combat:   P(Spearmen win) {scored.p_a_wins:.3f}  draw {scored.p_draw:.3f}  "
        f"P(Archers win) {scored.p_b_wins:.3f}"
    )


if __name__ == "__main__":
    main()
