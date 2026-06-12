"""End-to-end shooting demo: one unit shoots another.

Loads units, weapons, and armour from the data/ YAML tree, picks the
shooter's missile weapon from its equipment, resolves the shooting
chain, and prints the kill distribution.

Usage: uv run python scripts/shooting_demo.py [shooters] [attacker] [defender]
       (unit slugs default to elven-archers and elven-spearmen)
"""

import sys
from pathlib import Path

from avelorn.core.loading import load_yaml, load_yaml_dir
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
    """Run the demo with optional shooter count and unit slugs from argv."""
    shooters = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    attacker_slug = sys.argv[2] if len(sys.argv) > 2 else "elven-archers"
    defender_slug = sys.argv[3] if len(sys.argv) > 3 else "elven-spearmen"

    weapons = {w.name: w for w in load_yaml_dir(_DATA_DIR / "tow/weapons", Weapon)}
    armoury = {a.name: a for a in load_yaml_dir(_DATA_DIR / "tow/armour", Armour)}
    attacker = _load_unit("high-elf-realms", attacker_slug)
    defender = _load_unit("high-elf-realms", defender_slug)
    weapon = _missile_weapon(attacker, weapons)
    result = shoot_unit(attacker, defender, shooters=shooters, weapon=weapon, armoury=armoury)

    def fmt_target(target: int | None) -> str:
        return f"{target}+" if target is not None else "-"

    print(f"{shooters} {attacker.name} shoot {defender.name} with {weapon.name}s")
    print(f"  to hit:  {fmt_target(result.hit_target)}   (p = {result.p_hit:.3f})")
    print(f"  to wound: {fmt_target(result.wound_target)}  (p = {result.p_wound:.3f})")
    print(f"  armour:  {fmt_target(result.save_target)}")
    print(f"  per-shot unsaved wound: p = {result.p_unsaved:.3f}")
    print(f"  expected kills: {result.expected_wounds:.2f}")
    print()
    print("  kills  probability")
    for kills, p in enumerate(result.distribution):
        bar = "#" * round(p * 40)
        print(f"  {kills:>5}  {p:>10.3f}  {bar}")
    if result.notes:
        print()
        print("  not factored into the math:")
        for note in result.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
