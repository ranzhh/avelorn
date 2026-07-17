"""End-to-end shooting demo: one unit shoots another.

Loads units, weapons, and armour from the data/ YAML tree, resolves the
shooting chain, and prints the kill distribution.

Usage: uv run python scripts/shooting_demo.py [shooters] [attacker] [defender] [defenders]
       (unit slugs default to elven-archers and elven-spearmen; the weapon
       defaults to the longbow, overridable with --weapon)

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging

from avelorn.core.logging import configure_logging
from avelorn.tow.contingent import Movement
from avelorn.tow.game import TOWGame
from avelorn.tow.query import Comparator, Predicate, query_result


def main() -> None:
    """Parse argv, resolve one unit shooting another, and print the kill distribution."""
    parser = argparse.ArgumentParser(description="Shooting demo: one unit shoots another.")
    parser.add_argument(
        "shooters", nargs="?", type=int, default=3, help="number of shooting models"
    )
    parser.add_argument("attacker", nargs="?", default="elven-archers", help="attacker unit slug")
    parser.add_argument("defender", nargs="?", default="elven-spearmen", help="defender unit slug")
    parser.add_argument(
        "defenders",
        nargs="?",
        type=int,
        default=10,
        help="models in the target unit; caps casualties",
    )
    parser.add_argument("--weapon", default="longbow", help="weapon slug the attacker shoots with")
    parser.add_argument(
        "--distance", type=int, default=None, help="inches to the target (enables range rules)"
    )
    parser.add_argument(
        "--moved",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="whether the shooters moved this turn (default: stationary)",
    )
    parser.add_argument(
        "--battle-strength",
        type=int,
        default=None,
        help="defender models at the start of the battle (default: as fielded now)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="emit the DEBUG math trace to stderr"
    )
    args = parser.parse_args()
    if args.verbose:
        configure_logging(logging.DEBUG)

    game = TOWGame.load_data()
    attacker = game.field(game.units[args.attacker], args.shooters)
    if args.moved:
        attacker = attacker.after(Movement.march())
    defender = game.field(game.units[args.defender], args.defenders)
    weapon_name = game.weapons[args.weapon].name
    attacker = attacker.wielding(weapon_name)
    result = game.shooting.volley(attacker, defender, distance=args.distance)

    def fmt_target(target: int | None) -> str:
        return f"{target}+" if target is not None else "-"

    print(
        f"{attacker.models} {attacker.unit.name} shoot "
        f"{defender.models} {defender.unit.name} with {weapon_name}s\n"
        f"  to hit:  {fmt_target(result.hit_target)}   (p = {result.p_hit:.3f})\n"
        f"  to wound: {fmt_target(result.wound_target)}  (p = {result.p_wound:.3f})\n"
        f"  armour:  {fmt_target(result.save_target)}\n"
        f"  per-shot unsaved wound: p = {result.p_unsaved:.3f}\n"
        f"  expected casualties: {result.expected_casualties:.2f} of {defender.models}\n"
        f"\n  killed  probability"
    )
    for killed, p in enumerate(result.casualties):
        print(f"  {killed:>6}  {p:>10.3f}  {'#' * round(p * 40)}")

    # Exact distributional queries — the questions the game actually turns
    # on, not the average: one structured predicate over a named variable,
    # answered exactly by the querying layer.
    any_kill = query_result(result, "casualties", Predicate(Comparator.AT_LEAST, 1))
    wiped = query_result(result, "survivors", Predicate(Comparator.EXACTLY, 0))
    panic = game.shooting.make_panic_tests(result, defender, battle_strength=args.battle_strength)
    print(
        f"\n  exact queries:\n"
        f"  - P(at least one falls):       {any_kill:.3f}\n"
        f"  - P(unit wiped out):           {wiped:.3f}\n"
        f"\n  make panic tests:\n"
        f"  - P(test forced):              {panic.p_test:.3f}\n"
        f"  - P(holds):                    {panic.p_holds:.3f}\n"
        f"  - P(falls back in good order): {panic.p_falls_back:.3f}\n"
        f"  - P(flees):                    {panic.p_flees:.3f}\n"
        f"  - P(destroyed):                {panic.p_destroyed:.3f}"
    )
    if panic.reroll_from is not None:
        print(f"  (failed tests re-rolled: {panic.reroll_from})")

    if result.notes:
        print("\n  not factored into the math:")
        for note in result.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
