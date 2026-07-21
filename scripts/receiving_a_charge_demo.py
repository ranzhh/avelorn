"""Why Elven Spearmen would rather receive a charge than deliver one.

Two equal units of Elven Spearmen, thrusting spears in hand; one charges the
other. The charge lapses both of the charger's rank rules — Press of Battle
(its fighting rank falls from two ranks to one) and Fight in Extra Rank (no
supporting attack on a charging turn) — so it swings with a single rank. The
unit it hits, standing still, keeps all three: two ranks at full Attacks plus
one supporting rank. The charger strikes first for its charge Initiative
bonus, but with a third of the blows.

Then the payoff: the charger is stuck at one rank whichever weapon it draws,
and a thrusting spear and a hand weapon strike alike (Strength 3) — but a hand
weapon and shield turn on Parry (a 4+ save, not 5+), so the charger fares
measurably better trading its spear for them, the counterattack blunted.

Resolved exactly, no dice rolled. Prints who fights on each side, the striking
order, each side's casualty distribution, the combat result, and the charger's
weapon comparison — then the verdict.

Usage: uv run python scripts/receiving_a_charge_demo.py [spearmen] [charge_inches]

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging

from avelorn.core.dice import expected_value
from avelorn.core.logging import configure_logging
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame


def _resolve(game: "TOWGame", spearmen, models: int, inches: int, charger_weapon: str):
    """Charge ``models`` spearmen (armed with ``charger_weapon``) into standing spearmen.

    The charged keep their thrusting spears; only the charger's weapon in hand
    varies, so the two resolutions differ by the charger's arming alone.

    Returns:
        The engagement, the fought round, and its scored result.
    """
    chargers = game.field(spearmen, models).wielding(charger_weapon)
    receivers = game.field(spearmen, models).wielding("Thrusting Spear")
    engagement = game.movement.charge(chargers, receivers, Charge(inches, ChargeArc.FRONT))
    engagement.react()  # Hold — Spearmen carry no missile weapon to Stand & Shoot with
    melee = game.combat.fight(engagement)
    return engagement, melee, game.combat.result(melee)


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
    engagement, melee, scored = _resolve(
        game, spearmen, args.spearmen, args.charge_inches, "Thrusting Spear"
    )

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

    # The payoff: the charger is stuck at one rank whichever weapon it draws,
    # and a thrusting spear and a hand weapon both strike at Strength 3 — so the
    # attack is unchanged. But a hand weapon and shield turn on Parry (a 4+ save
    # in place of 5+), blunting the counterattack. Re-resolve so armed.
    _, hw_melee, hw_scored = _resolve(
        game, spearmen, args.spearmen, args.charge_inches, "Hand Weapon"
    )
    print(
        "\n  the charger's weapon (the charged keep their spears either way):\n"
        f"  - thrusting spear:      P(chargers win) {scored.p_a_wins:.3f}, "
        f"expected losses {expected_value(melee.a_casualties):.2f} of {args.spearmen}\n"
        f"  - hand weapon + shield: P(chargers win) {hw_scored.p_a_wins:.3f}, "
        f"expected losses {expected_value(hw_melee.a_casualties):.2f} of {args.spearmen}  "
        "(Parry: a 4+ save)\n"
        "\n  verdict: even charging into a single rank, the chargers do better with\n"
        "  hand weapon and shield — same blows struck, but Parry's 4+ save blunts\n"
        "  the counterattack the spear leaves them open to."
    )

    if melee.notes:
        print("\n  not factored into the math:")
        for note in melee.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
