"""End-to-end shooting demo: one unit shoots another.

Loads both units from the data/ YAML tree, picks the shooter's missile
weapon from its equipment, resolves the shooting chain, and prints the
kill distribution.

Usage: uv run python scripts/shooting_demo.py [shooters] [attacker] [defender]
       (unit slugs default to elven-archers and elven-spearmen)
"""

import sys
from pathlib import Path

import yaml

from avelorn.tow.combat.shooting import shoot_unit
from avelorn.tow.combat.weapons import LONGBOW, WARBOW, MissileWeapon
from avelorn.tow.schema.unit import Unit

_DATA_DIR = Path(__file__).parents[1] / "data"

# Equipment names are plain strings in the schema; callers map them to
# verified weapon profiles explicitly (see weapons.py).
_MISSILE_WEAPONS = {weapon.name: weapon for weapon in (LONGBOW, WARBOW)}


def _load_unit(army: str, slug: str) -> Unit:
    path = _DATA_DIR / f"tow/armies/{army}/units/{slug}.yaml"
    return Unit.model_validate(yaml.safe_load(path.read_text()))


def _missile_weapon(unit: Unit) -> MissileWeapon:
    for item in unit.equipment:
        weapon = _MISSILE_WEAPONS.get(item)
        if weapon is not None:
            return weapon
    known = ", ".join(_MISSILE_WEAPONS)
    raise SystemExit(f"{unit.name} carries no recognised missile weapon (known: {known})")


def main() -> None:
    """Run the demo with optional shooter count and unit slugs from argv."""
    shooters = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    attacker_slug = sys.argv[2] if len(sys.argv) > 2 else "elven-archers"
    defender_slug = sys.argv[3] if len(sys.argv) > 3 else "elven-spearmen"

    attacker = _load_unit("high-elf-realms", attacker_slug)
    defender = _load_unit("high-elf-realms", defender_slug)
    weapon = _missile_weapon(attacker)
    result = shoot_unit(attacker, defender, shooters=shooters, weapon=weapon)

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
