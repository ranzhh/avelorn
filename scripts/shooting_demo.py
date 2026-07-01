"""End-to-end shooting demo: one unit shoots another.

Loads units, weapons, and armour from the data/ YAML tree, picks the
shooter's missile weapon from its equipment, resolves the shooting
chain, and prints the kill distribution.

Usage: uv run python scripts/shooting_demo.py [shooters] [attacker] [defender] [defenders]
       (unit slugs default to elven-archers and elven-spearmen; with no
       defender count the kill distribution is left uncapped)

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging
from pathlib import Path

from avelorn.core.loading import load_yaml, load_yaml_dir
from avelorn.core.logging import configure_logging
from avelorn.tow.combat.query import Comparator, Predicate, query_result
from avelorn.tow.combat.shooting import shoot_unit
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon

_DATA_DIR = Path(__file__).parents[1] / "data"


def _load_unit(army: str, slug: str) -> Unit:
    return load_yaml(_DATA_DIR / f"tow/armies/{army}/units/{slug}.yaml", Unit)


def _missile_weapon(unit: Unit, weapons: dict[str, Weapon]) -> Weapon:
    for item in unit.equipment:
        weapon = weapons.get(item)
        if weapon is not None and weapon.missile_profile is not None:
            return weapon
    raise SystemExit(f"{unit.name} carries no missile weapon known under data/tow/weapons/")


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
        default=None,
        help="models in the target unit; caps casualties (uncapped if omitted)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="emit the DEBUG math trace to stderr"
    )
    args = parser.parse_args()
    if args.verbose:
        configure_logging(logging.DEBUG)

    shooters = args.shooters
    defenders = args.defenders
    weapons = {w.name: w for w in load_yaml_dir(_DATA_DIR / "tow/weapons", Weapon)}
    armoury = {a.name: a for a in load_yaml_dir(_DATA_DIR / "tow/armour", Armour)}
    attacker = _load_unit("high-elf-realms", args.attacker)
    defender = _load_unit("high-elf-realms", args.defender)
    weapon = _missile_weapon(attacker, weapons)
    result = shoot_unit(
        attacker, defender, shooters=shooters, weapon=weapon, armoury=armoury, defenders=defenders
    )

    def fmt_target(target: int | None) -> str:
        return f"{target}+" if target is not None else "-"

    target = f"{defenders} " if defenders is not None else ""
    print(f"{shooters} {attacker.name} shoot {target}{defender.name} with {weapon.name}s")
    print(f"  to hit:  {fmt_target(result.hit_target)}   (p = {result.p_hit:.3f})")
    print(f"  to wound: {fmt_target(result.wound_target)}  (p = {result.p_wound:.3f})")
    print(f"  armour:  {fmt_target(result.save_target)}")
    print(f"  per-shot unsaved wound: p = {result.p_unsaved:.3f}")
    if defenders is not None:
        print(
            f"  expected casualties: {result.expected_casualties:.2f} of {defenders}"
            f"   ({defenders - result.expected_casualties:.2f} survive)"
        )
    else:
        print(f"  expected kills: {result.expected_casualties:.2f}")
    print()
    print("  killed  probability")
    for killed, p in enumerate(result.casualties):
        bar = "#" * round(p * 40)
        print(f"  {killed:>6}  {p:>10.3f}  {bar}")

    # Exact distributional queries — the questions the game actually turns
    # on, not the average. Each is one structured predicate over a named
    # variable; the querying layer returns the exact probability.
    if defenders is not None:
        print()
        print("  exact queries:")
        wiped = query_result(result, "survivors", Predicate(Comparator.EXACTLY, 0))
        any_kill = query_result(result, "casualties", Predicate(Comparator.AT_LEAST, 1))
        at_most_3 = query_result(result, "survivors", Predicate(Comparator.AT_MOST, 3))
        print(f"  - P(at least one falls):       {any_kill:.3f}")
        print(f"  - P(at most 3 survive):        {at_most_3:.3f}")
        print(f"  - P(unit wiped out):           {wiped:.3f}")

    if result.notes:
        print()
        print("  not factored into the math:")
        for note in result.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
