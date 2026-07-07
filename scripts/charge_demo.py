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
from avelorn.tow.combat.charge import StandAndShoot, charge
from avelorn.tow.combat.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.combat.melee import combat_result, effective_initiative
from avelorn.tow.combat.morale import break_test
from avelorn.tow.combat.query import Comparator, Predicate, evaluate, fight_distributions
from avelorn.tow.data import TOWRepository
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

    repo = TOWRepository()
    spearmen_unit = repo.units["elven-spearmen"]
    archers_unit = repo.units["elven-archers"]
    # The scene fixes each unit's weapon for the phase it acts in: the
    # Archers shoot the Longbow, then defend with a Hand Weapon; the Spearmen
    # charge home with the Thrusting Spear.
    spear = repo.weapons["thrusting-spear"]
    hand_weapon = repo.weapons["hand-weapon"]
    longbow = repo.weapons["longbow"]

    spearmen = Contingent.field(
        spearmen_unit, args.spearmen, weapons=repo.weapons, armoury=repo.armoury, rules=repo.rules
    )
    archers = Contingent.field(
        archers_unit, args.archers, weapons=repo.weapons, armoury=repo.armoury, rules=repo.rules
    )
    move = Charge(args.charge_inches, ChargeArc.FRONT)

    outcome = charge(
        spearmen,
        archers,
        move=move,
        charger_weapon=spear,
        target_weapon=hand_weapon,
        reaction=StandAndShoot(longbow),
        rules=repo.rules,
    )
    reaction = outcome.reaction
    assert reaction is not None  # a StandAndShoot reaction was declared
    melee = outcome.melee
    scored = combat_result(melee)
    breaks = break_test(scored, spearmen_unit, archers_unit)

    movement = spearmen_unit.profiles[0][Characteristic.MOVEMENT]
    init = spearmen_unit.profiles[0][Characteristic.INITIATIVE] or 0
    charged_init = effective_initiative(spearmen, move).value
    bonus = charged_init - init
    inches = args.charge_inches
    print(f'{args.spearmen} Elven Spearmen charge {args.archers} Elven Archers ({inches}")')
    if movement is None or inches >= movement:
        print("  charge reaction: the Archers Stand & Shoot (bow), then Hold")
    else:
        print(
            f"  charge reaction: gap < Movement {movement}, "
            "no Stand & Shoot possible; assumed anyway"
        )
    print()

    print("  Stand & Shoot (Archers -> charging Spearmen, -1 To Hit, no long range):")
    _print_casualties("Spearmen", reaction.casualties, args.spearmen)
    print()

    if melee.first_striker is spearmen:
        order = f"Spearmen first (I{init} +{bonus} charge = I{charged_init} vs Archers I{init})"
    else:
        order = f'simultaneous (both I{init}; the {inches}" charge adds +{bonus})'
    print(f"  striking order: {order}")
    print("  (assumes every fighter is in base contact at full Attacks;")
    print("   fighting ranks & supporting attacks not yet modelled — #28)")
    print()

    _print_casualties("Spearmen (A, melee)", melee.a_casualties, args.spearmen)
    print()
    _print_casualties("Archers (B, melee)", melee.b_casualties, args.archers)
    print()

    # Expectations add whatever the correlation, so the total the chargers
    # lose across the sequence is the Stand & Shoot mean plus the melee mean.
    shot = expected_value(reaction.casualties)
    slain = expected_value(melee.a_casualties)
    print(f"  expected Spearmen lost over the whole charge: {shot + slain:.2f} of {args.spearmen}")
    print(f"  (Stand & Shoot {shot:.2f} + melee {slain:.2f})")
    print()

    print("  combat result (melee only):")
    print(f"  - P(Spearmen win): {scored.p_a_wins:.3f}")
    print(f"  - P(draw):         {scored.p_draw:.3f}")
    print(f"  - P(Archers win):  {scored.p_b_wins:.3f}")
    print()

    print("  break test (only the loser tests):")
    for label, side in (("Spearmen", breaks.a), ("Archers", breaks.b)):
        lost = side.p_gives_ground + side.p_falls_back + side.p_breaks
        print(
            f"  - {label} (loses {lost:.3f}): gives ground {side.p_gives_ground:.3f}, "
            f"falls back {side.p_falls_back:.3f}, breaks {side.p_breaks:.3f}"
        )
    print(f"  - draw, neither tests: {breaks.p_draw:.3f}")
    print()

    dists = fight_distributions(melee)
    print("  exact queries:")
    archers_bloodied = evaluate(dists["b_casualties"], Predicate(Comparator.AT_LEAST, 1))
    spearmen_clean = evaluate(dists["a_survivors"], Predicate(Comparator.EXACTLY, args.spearmen))
    print(f"  - P(Archers lose at least one in the melee): {archers_bloodied:.3f}")
    print(f"  - P(no Spearman falls in the melee):         {spearmen_clean:.3f}")

    if melee.notes:
        print()
        print("  not factored into the math:")
        for note in melee.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
