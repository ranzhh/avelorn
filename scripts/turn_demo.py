"""End-to-end turn-walk demo: walk one player-turn phase by phase.

Deploys two units and walks the turn — Strategy, Movement (the Spearmen charge
the Archers, who Stand & Shoot), Shooting (both are now locked in combat, so
there is nothing to shoot), Combat (the engagement the charge formed is fought
and scored). It shows the turn as the rulebook plays it: a charge is a
Movement-phase event that locks the units in combat, and the melee is fought in
the Combat phase.

Usage: uv run python scripts/turn_demo.py [spearmen] [archers] [charge_inches]

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging

from avelorn.core.dice import expected_value
from avelorn.core.logging import configure_logging
from avelorn.tow.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot


def main() -> None:
    """Parse argv, walk a turn, and print each phase's outcome."""
    parser = argparse.ArgumentParser(description="Turn-walk demo: Spearmen charge Archers.")
    parser.add_argument("spearmen", nargs="?", type=int, default=20, help="charging Spearmen")
    parser.add_argument("archers", nargs="?", type=int, default=10, help="defending Archers")
    parser.add_argument("charge_inches", nargs="?", type=int, default=8, help="inches charged")
    parser.add_argument("-v", "--verbose", action="store_true", help="emit the DEBUG math trace")
    args = parser.parse_args()
    if args.verbose:
        configure_logging(logging.DEBUG)

    game = TOWGame.load_data()
    spearmen = Contingent.deploy("elven-spearmen", args.spearmen, data=game.repository).wielding(
        "Thrusting Spear"
    )
    archers = Contingent.deploy("elven-archers", args.archers, data=game.repository).wielding(
        "Hand Weapon"
    )

    turn = game.turn()

    with turn.strategy():
        print("Strategy phase: nothing modelled.\n")

    with turn.movement() as mv:
        move = Charge(args.charge_inches, ChargeArc.FRONT)
        engagement = mv.charge(spearmen, archers, move)
        reaction = engagement.react(StandAndShoot())  # fires the Archers' sole missile weapon
        inches = args.charge_inches
        print(
            f'Movement phase: {args.spearmen} Spearmen charge {args.archers} Archers ({inches}").'
        )
        if reaction is not None:
            felled = expected_value(reaction.casualties)
            print(f"  Archers Stand & Shoot: {felled:.2f} chargers felled on average.\n")

    with turn.shooting():
        print("Shooting phase: both units are locked in combat — no shots.\n")

    with turn.combat() as cb:
        result = cb.result(cb.fight(engagement))
        print("Combat phase: fighting the engagement the charge formed.")
        print(
            f"  P(Spearmen win) {result.p_a_wins:.3f}   "
            f"P(draw) {result.p_draw:.3f}   "
            f"P(Archers win) {result.p_b_wins:.3f}"
        )


if __name__ == "__main__":
    main()
