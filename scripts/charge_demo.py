"""End-to-end charge demo: Elven Spearmen charge Elven Archers.

The full sequence, resolved exactly (no dice rolled):

1. The Spearmen declare a charge over ``charge_inches``.
2. The Archers react with Stand & Shoot, loosing their bows at the chargers
   as they close (-1 To Hit, no long-range penalty).
3. The survivors fight the combat round — the Spearmen striking first for
   their charge Initiative bonus, then the Archers striking back with a hand
   weapon. The melee is resolved over the whole Stand & Shoot casualty
   distribution, so fewer surviving chargers means fewer attacks.

Prints the Stand & Shoot toll, the striking order, each side's melee
casualty distribution, the combat result, both Break tests, exact
distributional queries, and everything the math does not yet factor.

Usage: uv run python scripts/charge_demo.py [spearmen] [archers] [charge_inches]

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging

from avelorn.core.dice import expected_value
from avelorn.core.logging import configure_logging
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot
from avelorn.tow.query import Comparator, Predicate, evaluate, fight_distributions
from avelorn.tow.schema.unit import Characteristic


def _print_casualties(label: str, casualties: list[float], models: int) -> None:
    print(f"  {label} casualties:")
    print(f"    expected: {expected_value(casualties):.2f} of {models}")
    print("    killed  probability")
    for killed, p in enumerate(casualties):
        bar = "#" * round(p * 40)
        print(f"    {killed:>6}  {p:>10.3f}  {bar}")


def main() -> None:
    """Parse argv, resolve the charge sequence, and print the outcome."""
    parser = argparse.ArgumentParser(description="Charge demo: Spearmen charge Archers.")
    parser.add_argument("spearmen", nargs="?", type=int, default=10, help="charging Spearmen")
    parser.add_argument("archers", nargs="?", type=int, default=10, help="defending Archers")
    parser.add_argument(
        "charge_inches", nargs="?", type=int, default=8, help="inches the Spearmen charged"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="emit the DEBUG math trace to stderr"
    )
    args = parser.parse_args()
    if args.verbose:
        configure_logging(logging.DEBUG)

    game = TOWGame.load_data()
    spearmen_unit = game.units["elven-spearmen"]
    archers_unit = game.units["elven-archers"]
    # The scene arms each unit for the melee it heads into: the Spearmen
    # charge home with the Thrusting Spear, the Archers defend with a Hand
    # Weapon. The Stand & Shoot fires the Archers' sole missile weapon (their
    # Longbow) without naming it.
    spearmen = game.field(spearmen_unit, args.spearmen).wielding("Thrusting Spear")
    archers = game.field(archers_unit, args.archers).wielding("Hand Weapon")
    move = Charge(args.charge_inches, ChargeArc.FRONT)

    engagement = game.movement.charge(spearmen, archers, move)
    reaction = engagement.react(StandAndShoot())
    assert reaction is not None  # a StandAndShoot reaction was declared
    melee = game.combat.fight(engagement)
    scored = game.combat.result(melee)
    breaks = game.combat.break_test(scored, spearmen_unit, archers_unit)

    movement = spearmen_unit.profiles[0][Characteristic.MOVEMENT]
    charged_init = melee.a_initiative.value
    archers_init = melee.b_initiative.value
    inches = args.charge_inches
    print(f'{args.spearmen} Elven Spearmen charge {args.archers} Elven Archers ({inches}")')
    if movement is None or inches >= movement:
        print("  charge reaction: the Archers Stand & Shoot (bow), then Hold\n")
    else:
        print(
            f"  charge reaction: gap < Movement {movement}, "
            "no Stand & Shoot possible; assumed anyway\n"
        )
    print("  Stand & Shoot (Archers -> charging Spearmen, -1 To Hit, no long range):")
    _print_casualties("Spearmen", reaction.casualties, args.spearmen)
    print()

    if melee.first_striker is not None and melee.first_striker.unit is spearmen_unit:
        order = f"Spearmen first (effective I{charged_init} vs Archers I{archers_init})"
    else:
        order = f"simultaneous (both at effective I{charged_init})"
    print(f"  striking order: {order}\n")

    _print_casualties("Spearmen (A, melee)", melee.a_casualties, args.spearmen)
    print()
    _print_casualties("Archers (B, melee)", melee.b_casualties, args.archers)

    # Expectations add whatever the correlation, so the total the chargers
    # lose across the sequence is the Stand & Shoot mean plus the melee mean.
    shot = expected_value(reaction.casualties)
    slain = expected_value(melee.a_casualties)
    print(
        f"\n  expected Spearmen lost over the whole charge: "
        f"{shot + slain:.2f} of {args.spearmen} (Stand & Shoot {shot:.2f} + melee {slain:.2f})\n"
        f"\n  combat result (melee only):\n"
        f"  - P(Spearmen win): {scored.p_a_wins:.3f}\n"
        f"  - P(draw):         {scored.p_draw:.3f}\n"
        f"  - P(Archers win):  {scored.p_b_wins:.3f}\n"
        f"\n  break test (only the loser tests):"
    )
    for label, side in (("Spearmen", breaks.a), ("Archers", breaks.b)):
        lost = side.p_gives_ground + side.p_falls_back + side.p_breaks
        print(
            f"  - {label} (loses {lost:.3f}): gives ground {side.p_gives_ground:.3f}, "
            f"falls back {side.p_falls_back:.3f}, breaks {side.p_breaks:.3f}"
        )
    print(f"  - draw, neither tests: {breaks.p_draw:.3f}")

    dists = fight_distributions(melee)
    archers_bloodied = evaluate(dists["b_casualties"], Predicate(Comparator.AT_LEAST, 1))
    spearmen_clean = evaluate(dists["a_survivors"], Predicate(Comparator.EXACTLY, args.spearmen))
    print(
        f"\n  exact queries:\n"
        f"  - P(Archers lose at least one in the melee): {archers_bloodied:.3f}\n"
        f"  - P(no Spearman falls in the melee):         {spearmen_clean:.3f}"
    )

    if melee.notes:
        print("\n  not factored into the math:")
        for note in melee.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
