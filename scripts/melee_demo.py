"""End-to-end close-combat demo: two units fight a round.

Loads both units, armour, and rules from the data/ YAML tree, resolves one
round of combat (strike order, the return strike, combat result, and each
side's Break test) with both sides wielding the weapon given by --weapon,
and prints the outcome distributions.

Usage: uv run python scripts/melee_demo.py [a_fighters] [unit_a] [unit_b] [b_fighters]
       (unit slugs default to elven-spearmen on both sides; the weapon
       defaults to the thrusting spear, overridable with --weapon)

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging

from avelorn.core.dice import expected_value
from avelorn.core.logging import configure_logging
from avelorn.tow.combat.context import CombatContext
from avelorn.tow.combat.contingent import Contingent
from avelorn.tow.combat.query import Comparator, Predicate, evaluate, fight_distributions
from avelorn.tow.data import TOWRepository
from avelorn.tow.game import Game


def _print_casualties(label: str, casualties: list[float], fighters: int) -> None:
    print(f"  {label} casualties:")
    print(f"    expected: {expected_value(casualties):.2f} of {fighters}")
    print("    killed  probability")
    for killed, p in enumerate(casualties):
        bar = "#" * round(p * 40)
        print(f"    {killed:>6}  {p:>10.3f}  {bar}")


def main() -> None:
    """Parse argv, resolve one round of close combat, and print the outcome."""
    parser = argparse.ArgumentParser(description="Close-combat demo: two units fight a round.")
    parser.add_argument(
        "a_fighters", nargs="?", type=int, default=5, help="models fighting on side A"
    )
    parser.add_argument("unit_a", nargs="?", default="elven-spearmen", help="side A unit slug")
    parser.add_argument("unit_b", nargs="?", default="elven-spearmen", help="side B unit slug")
    parser.add_argument(
        "b_fighters", nargs="?", type=int, default=5, help="models fighting on side B"
    )
    parser.add_argument(
        "--weapon", default="thrusting-spear", help="weapon slug both sides fight with"
    )
    parser.add_argument(
        "--first-round",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="whether this is the combat's first round (omit = unknown)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="emit the DEBUG math trace to stderr"
    )
    args = parser.parse_args()
    if args.verbose:
        configure_logging(logging.DEBUG)

    repo = TOWRepository()
    unit_a = repo.units[args.unit_a]
    unit_b = repo.units[args.unit_b]
    weapon_a = weapon_b = repo.weapons[args.weapon]

    a = Contingent.field(
        unit_a, args.a_fighters, weapons=repo.weapons, armoury=repo.armoury, rules=repo.rules
    )
    b = Contingent.field(
        unit_b, args.b_fighters, weapons=repo.weapons, armoury=repo.armoury, rules=repo.rules
    )
    game = Game.assemble(repo.rules)
    result = game.combat.fight(
        a,
        b,
        a_weapon=weapon_a,
        b_weapon=weapon_b,
        context=CombatContext(first_round=args.first_round),
    )
    scored = game.combat.result(result)
    breaks = game.combat.break_test(scored, unit_a, unit_b)

    init_a = result.a_initiative.value
    init_b = result.b_initiative.value
    print(
        f"{args.a_fighters} {unit_a.name} fight {args.b_fighters} {unit_b.name} "
        f"({weapon_a.name} vs {weapon_b.name})"
    )
    if result.first_striker is None:
        print(f"  striking order: simultaneous (both Initiative {init_a})")
    else:
        first = "A" if result.first_striker is a else "B"
        print(f"  striking order: {first} strikes first (Initiative {init_a} vs {init_b})")
    print("  (assumes every fighter is in base contact at full Attacks;")
    print("   fighting ranks & supporting attacks not yet modelled — #28)")
    print()

    _print_casualties(f"{unit_a.name} (A)", result.a_casualties, args.a_fighters)
    print()
    _print_casualties(f"{unit_b.name} (B)", result.b_casualties, args.b_fighters)

    print()
    print("  combat result:")
    print(f"  - P(A wins):  {scored.p_a_wins:.3f}")
    print(f"  - P(draw):    {scored.p_draw:.3f}")
    print(f"  - P(B wins):  {scored.p_b_wins:.3f}")

    print()
    print("  break test (only the loser tests):")
    for label, side in (("A", breaks.a), ("B", breaks.b)):
        lost = side.p_gives_ground + side.p_falls_back + side.p_breaks
        print(
            f"  - {label} (loses {lost:.3f}): gives ground {side.p_gives_ground:.3f}, "
            f"falls back {side.p_falls_back:.3f}, breaks {side.p_breaks:.3f}"
        )
    print(f"  - draw, neither tests: {breaks.p_draw:.3f}")

    # Exact distributional queries over the round, via the query layer.
    dists = fight_distributions(result)
    print()
    print("  exact queries:")
    b_bloodied = evaluate(dists["b_casualties"], Predicate(Comparator.AT_LEAST, 1))
    a_unscathed = evaluate(dists["a_survivors"], Predicate(Comparator.EXACTLY, args.a_fighters))
    print(f"  - P(B loses at least one): {b_bloodied:.3f}")
    print(f"  - P(A comes through unscathed): {a_unscathed:.3f}")

    if result.notes:
        print()
        print("  not factored into the math:")
        for note in result.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
