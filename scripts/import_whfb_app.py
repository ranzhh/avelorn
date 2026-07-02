"""Import units, weapons, armour, and rules from tow.whfb.app into data/.

uv run python scripts/import_whfb_app.py unit elven-archers
uv run python scripts/import_whfb_app.py unit elven-archers --army high-elf-realms
uv run python scripts/import_whfb_app.py army high-elf-realms
uv run python scripts/import_whfb_app.py weapon longbow
uv run python scripts/import_whfb_app.py armour light-armour
uv run python scripts/import_whfb_app.py rule armour-bane
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from avelorn.core.logging import configure_logging
from avelorn.tow.importers.whfb_app.client import BASE_URL, WhfbAppClient, WhfbAppError
from avelorn.tow.importers.whfb_app.equipment import parse_armour, parse_weapon
from avelorn.tow.importers.whfb_app.parse import UnsupportedUnit, WhfbParseError, parse_unit
from avelorn.tow.importers.whfb_app.rules import parse_special_rule
from avelorn.tow.importers.whfb_app.yamlout import (
    armour_to_yaml,
    rule_to_yaml,
    unit_to_yaml,
    weapon_to_yaml,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Run the importer CLI.

    Returns:
        The process exit code.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", type=Path, default=Path("data"))
    common.add_argument("--dry-run", action="store_true", help="print YAML instead of writing")

    parser = argparse.ArgumentParser(prog="import_whfb_app")
    sub = parser.add_subparsers(dest="command", required=True)

    unit_cmd = sub.add_parser("unit", parents=[common], help="import a single unit by slug")
    unit_cmd.add_argument("slug")
    unit_cmd.add_argument(
        "--army", help="army slug; resolved from the unit's associations if omitted"
    )

    army_cmd = sub.add_parser("army", parents=[common], help="import every unit of an army")
    army_cmd.add_argument("slug")

    weapon_cmd = sub.add_parser("weapon", parents=[common], help="import a weapon by slug")
    weapon_cmd.add_argument("slug")

    armour_cmd = sub.add_parser("armour", parents=[common], help="import an armour item by slug")
    armour_cmd.add_argument("slug")

    rule_cmd = sub.add_parser("rule", parents=[common], help="import a special rule by slug")
    rule_cmd.add_argument("slug")

    args = parser.parse_args(argv)
    configure_logging()
    client = WhfbAppClient()
    try:
        if args.command == "unit":
            ok = _import_unit(client, args.slug, args.army, args.data_dir, args.dry_run)
        elif args.command == "army":
            ok = _import_army(client, args.slug, args.data_dir, args.dry_run)
        elif args.command == "rule":
            ok = _import_rule(client, args.slug, args.data_dir, args.dry_run)
        else:
            ok = _import_equipment(client, args.command, args.slug, args.data_dir, args.dry_run)
    except WhfbAppError:
        logger.exception("import failed")
        return 1
    return 0 if ok else 1


def _import_equipment(
    client: WhfbAppClient, kind: str, slug: str, data_dir: Path, dry_run: bool
) -> bool:
    entry = client.weapons_of_war_entry(slug)
    try:
        if kind == "weapon":
            result = parse_weapon(entry)
            text = weapon_to_yaml(result.weapon, source_url=f"{BASE_URL}/weapons-of-war/{slug}")
        else:
            result = parse_armour(entry)
            text = armour_to_yaml(result.armour, source_url=f"{BASE_URL}/weapons-of-war/{slug}")
    except WhfbParseError:
        logger.exception("%s: parse failed", slug)
        return False
    for warning in result.warnings:
        logger.warning("%s: %s", slug, warning)
    if dry_run:
        print(text)  # generated YAML is the program's payload -> stdout
        return True
    subdir = "weapons" if kind == "weapon" else "armour"
    path = data_dir / "tow" / subdir / f"{slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    logger.info("wrote %s", path)
    return True


def _import_rule(client: WhfbAppClient, slug: str, data_dir: Path, dry_run: bool) -> bool:
    entry = client.special_rule_entry(slug)
    try:
        result = parse_special_rule(entry)
    except WhfbParseError:
        logger.exception("%s: parse failed", slug)
        return False
    for warning in result.warnings:
        logger.warning("%s: %s", slug, warning)
    text = rule_to_yaml(result.rule, source_url=f"{BASE_URL}/special-rules/{slug}")
    if dry_run:
        print(text)  # generated YAML is the program's payload -> stdout
        return True
    path = data_dir / "tow" / "rules" / f"{slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    logger.info("wrote %s", path)
    return True


def _import_unit(
    client: WhfbAppClient, slug: str, army: str | None, data_dir: Path, dry_run: bool
) -> bool:
    entry = client.unit_entry(slug)
    if army is None:
        army = _resolve_army(client, entry)
        logger.info("%s: army resolved to %r", slug, army)
    return _write_unit(entry, army, data_dir, dry_run)


def _import_army(client: WhfbAppClient, army: str, data_dir: Path, dry_run: bool) -> bool:
    slugs = client.army_unit_slugs(army)
    if not slugs:
        logger.error("army %r lists no units", army)
        return False
    ok = True
    for slug in slugs:
        ok = _write_unit(client.unit_entry(slug), army, data_dir, dry_run) and ok
    return ok


def _write_unit(entry: dict, army: str, data_dir: Path, dry_run: bool) -> bool:
    slug = entry["fields"]["slug"]
    try:
        result = parse_unit(entry)
    except UnsupportedUnit as err:
        logger.warning("%s: skipped (%s)", slug, err)
        return True
    except WhfbParseError:
        logger.exception("%s: parse failed", slug)
        return False
    for warning in result.warnings:
        logger.warning("%s: %s", slug, warning)
    text = unit_to_yaml(result.unit, source_url=f"{BASE_URL}/unit/{slug}")
    if dry_run:
        print(text)  # generated YAML is the program's payload -> stdout
        return True
    path = data_dir / "tow" / "armies" / army / "units" / f"{slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    logger.info("wrote %s", path)
    return True


def _resolve_army(client: WhfbAppClient, entry: dict) -> str:
    """Pick the unit's army from its associations.

    `association` mixes source books and armies (e.g. "Forces of Fantasy"
    and "High Elf Realms"); the army is the one whose page lists the unit.

    Returns:
        The army slug.

    Raises:
        WhfbAppError: No association page lists the unit.
    """
    slug = entry["fields"]["slug"]
    candidates = [a["fields"]["slug"] for a in reversed(entry["fields"].get("association", []))]
    for candidate in candidates:
        try:
            if slug in client.army_unit_slugs(candidate):
                return candidate
        except WhfbAppError:
            continue
    raise WhfbAppError(
        f"could not resolve an army for {slug!r} from associations {candidates!r}; pass --army"
    )


if __name__ == "__main__":
    sys.exit(main())
