"""Why Elven Spearmen would rather receive a charge than deliver one.

Two equal units of Elven Spearmen, thrusting spears in hand; one charges the
other. The charge lapses both of the charger's rank rules — Press of Battle
(its fighting rank falls from two ranks to one) and Fight in Extra Rank (no
supporting attack on a charging turn) — so it swings with a single rank. The
unit it hits, standing still, keeps all three: two ranks at full Attacks plus
one supporting rank. The charger strikes first for its charge Initiative
bonus, but with a third of the blows.

Resolved exactly, no dice rolled. Prints who fights on each side, the striking
order, each side's casualty distribution, and the combat result — then the
verdict.

Usage: uv run python scripts/receiving_a_charge_demo.py [spearmen] [charge_inches]

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging

from avelorn.core.dice import expected_value
from avelorn.core.logging import configure_logging
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame


def _print_casualties(label: str, casualties: list[float], models: int) -> None:
    print(f"  {label} casualties:")
    print(f"    expected: {expected_value(casualties):.2f} of {models}")
    print("    killed  probability")
    for killed, p in enumerate(casualties):
        bar = "#" * round(p * 40)
        print(f"    {killed:>6}  {p:>10.3f}  {bar}")


def main() -> None:
    """Parse argv, resolve one spearmen-on-spearmen charge, and print the verdict."""
    parser = argparse.ArgumentParser(
        description="Why Spearmen prefer being charged: equal units, one charges the other."
    )
    parser.add_argument("spearmen", nargs="?", type=int, default=20, help="models on each side")
    parser.add_argument(
        "charge_inches", nargs="?", type=int, default=8, help="inches the chargers moved"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="emit the DEBUG math trace to stderr"
    )
    args = parser.parse_args()
    if args.verbose:
        configure_logging(logging.DEBUG)

    game = TOWGame.load_data()
    spearmen = game.units["elven-spearmen"]
    chargers = game.field(spearmen, args.spearmen).wielding("Thrusting Spear")
    receivers = game.field(spearmen, args.spearmen).wielding("Thrusting Spear")

    move = Charge(args.charge_inches, ChargeArc.FRONT)
    engagement = game.movement.charge(chargers, receivers, move)
    engagement.react()  # Hold — Spearmen carry no missile weapon to Stand & Shoot with
    melee = game.combat.fight(engagement)
    scored = game.combat.result(melee)

    # The engagement carries the *charged* copy of the chargers (rank rules
    # lapsed); the receivers stand as fielded — so ask each for what it throws.
    charging, standing = engagement.a, engagement.b
    print(
        f"{args.spearmen} Elven Spearmen charge {args.spearmen} Elven Spearmen "
        f'({args.charge_inches}")\n'
    )
    print("  who fights (thrusting spears, five wide):")
    print(
        f"  - chargers:    {charging.fighting_rank():>2} in the fighting rank, "
        f"{charging.melee_attacks():>2} attacks  "
        "(Press of Battle + Fight in Extra Rank lapse on a charge)"
    )
    print(
        f"  - the charged: {standing.fighting_rank():>2} in the fighting rank, "
        f"{standing.melee_attacks():>2} attacks  "
        "(two full ranks + one supporting rank)"
    )

    first = melee.first_striker
    a_init, b_init = melee.a_initiative.value, melee.b_initiative.value
    if first is charging:
        order = f"chargers strike first (I{a_init} vs I{b_init}), for the charge Initiative bonus"
    elif first is None:
        order = "simultaneous"
    else:
        order = f"the charged strike first (I{b_init} vs I{a_init})"
    print(f"\n  striking order: {order}\n")

    _print_casualties("chargers (A)", melee.a_casualties, args.spearmen)
    print()
    _print_casualties("the charged (B)", melee.b_casualties, args.spearmen)

    print(
        f"\n  combat result:\n"
        f"  - P(chargers win):    {scored.p_a_wins:.3f}\n"
        f"  - P(draw):            {scored.p_draw:.3f}\n"
        f"  - P(the charged win): {scored.p_b_wins:.3f}"
    )
    print(
        "\n  verdict: Elven Spearmen would rather receive a charge than deliver one.\n"
        "  Even striking first, a charging unit swings with a single rank while the\n"
        "  unit it hits swings with three."
    )

    if melee.notes:
        print("\n  not factored into the math:")
        for note in melee.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
