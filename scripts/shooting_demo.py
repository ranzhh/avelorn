"""End-to-end shooting demo: units shoot a target.

Loads units, weapons, and armour from the data/ YAML tree, resolves the
shooting chain for one unit (the full chain, the exact queries, the panic
test), then adds a second unit to the same target and composes their tolls.

Two units shooting one target resolve one after the other, casualties removed
between — so the joining unit fires at the *survivors* of the first. That is a
``bind``: the second toll folds onto the first's casualty distribution, giving
one exact combined distribution with no manual convolution. Chain a third and
it is another bind; the fold goes as deep as you like.

Usage: uv run python scripts/shooting_demo.py [shooters] [attacker] [defender] [defenders]
       (unit slugs default to elven-archers and elven-spearmen; with no
       --weapon the attacker fires its sole missile weapon; --join adds the
       second unit, default sisters-of-avelorn)

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging

from avelorn.core.distribution import Distribution
from avelorn.core.logging import configure_logging
from avelorn.tow.contingent import Movement
from avelorn.tow.game import TOWGame


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
    parser.add_argument(
        "--weapon",
        default=None,
        help="weapon slug to shoot with; defaults to the unit's sole missile weapon",
    )
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
        "--join",
        default="sisters-of-avelorn",
        help="a second unit that joins the volley (slug); its fire composes onto the first's",
    )
    parser.add_argument(
        "--join-shooters",
        type=int,
        default=None,
        help="models in the joining unit (default: same as shooters)",
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
    # With no --weapon the unit fires its sole missile weapon (shooting's
    # default); a slug arms it explicitly, as a unit carrying several must.
    if args.weapon is not None:
        attacker = attacker.wielding(game.weapons[args.weapon].name)
    result = game.shooting.volley(attacker, defender, distance=args.distance)
    weapon_name = attacker.shooting_weapon().name

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

    # Exact distributional queries — the questions the game actually turns on,
    # not the average: a predicate over the outcome, answered exactly. The
    # casualty pmf lifts into a Distribution; survivors == 0 is casualties at
    # the unit's full size.
    casualties = Distribution.from_counts(result.casualties)
    any_kill = casualties.prob(lambda k: k >= 1)
    wiped = casualties.prob(lambda k: k == defender.models)
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

    # A second unit joins the volley at the same target. It fires at the
    # survivors of the first, so its toll binds onto the first's casualty
    # distribution — one exact combined distribution, no manual convolution.
    join_unit = game.units[args.join]
    join_shooters = args.join_shooters if args.join_shooters is not None else args.shooters

    def add_join(dead: int) -> Distribution[int]:
        remaining = defender.models - dead
        if remaining == 0:
            return Distribution.pure(dead)  # target already wiped — nothing left to shoot
        volley = game.shooting.volley(
            game.field(join_unit, join_shooters),
            game.field(defender.unit, remaining),
            distance=args.distance,
        )
        return Distribution.from_counts(volley.casualties).map(lambda more: dead + more)

    combined = Distribution.from_counts(result.casualties).bind(add_join)
    print(
        f"\n  {join_shooters} {join_unit.name} join the volley — their fire composes onto the "
        f"{attacker.models} {attacker.unit.name}'\n  toll (bind over the survivors):\n"
        f"  - combined expected casualties: {combined.expect(float):.2f} of {defender.models}\n"
        f"  - P(at least one falls):        {combined.prob(lambda k: k >= 1):.3f}\n"
        f"  - P(unit wiped out):            {combined.prob(lambda k: k == defender.models):.3f}"
    )


if __name__ == "__main__":
    main()
