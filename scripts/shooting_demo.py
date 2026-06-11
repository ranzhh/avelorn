"""End-to-end shooting demo: Elven Archers shoot Elven Spearmen.

Loads both units from the data/ YAML tree, resolves the shooting chain,
and prints the kill distribution.

Usage: uv run python scripts/shooting_demo.py [shooters]
"""

import sys
from pathlib import Path

import yaml

from avelorn.tow.combat.shooting import shoot_unit
from avelorn.tow.combat.weapons import LONGBOW
from avelorn.tow.schema.unit import Unit

_DATA_DIR = Path(__file__).parents[1] / "data"


def _load_unit(army: str, slug: str) -> Unit:
    path = _DATA_DIR / f"tow/armies/{army}/units/{slug}.yaml"
    return Unit.model_validate(yaml.safe_load(path.read_text()))


def main() -> None:
    """Run the demo with an optional shooter count from argv."""
    shooters = int(sys.argv[1]) if len(sys.argv) > 1 else 3

    archers = _load_unit("high-elf-realms", "elven-archers")
    spearmen = _load_unit("high-elf-realms", "elven-spearmen")
    result = shoot_unit(archers, spearmen, shooters=shooters, weapon=LONGBOW)

    def fmt_target(target: int | None) -> str:
        return f"{target}+" if target is not None else "-"

    print(f"{shooters} {archers.name} shoot {spearmen.name} with {LONGBOW.name}s")
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
