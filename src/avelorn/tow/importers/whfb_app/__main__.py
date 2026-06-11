"""Import units from tow.whfb.app into data/.

python -m avelorn.tow.importers.whfb_app unit elven-archers
python -m avelorn.tow.importers.whfb_app unit elven-archers --army high-elf-realms
python -m avelorn.tow.importers.whfb_app army high-elf-realms
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .client import BASE_URL, WhfbAppClient, WhfbAppError
from .parse import UnsupportedUnit, WhfbParseError, parse_unit
from .yamlout import unit_to_yaml


def main(argv: list[str] | None = None) -> int:
    """Run the importer CLI.

    Returns:
        The process exit code.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", type=Path, default=Path("data"))
    common.add_argument("--dry-run", action="store_true", help="print YAML instead of writing")

    parser = argparse.ArgumentParser(prog="python -m avelorn.tow.importers.whfb_app")
    sub = parser.add_subparsers(dest="command", required=True)

    unit_cmd = sub.add_parser("unit", parents=[common], help="import a single unit by slug")
    unit_cmd.add_argument("slug")
    unit_cmd.add_argument(
        "--army", help="army slug; resolved from the unit's associations if omitted"
    )

    army_cmd = sub.add_parser("army", parents=[common], help="import every unit of an army")
    army_cmd.add_argument("slug")

    args = parser.parse_args(argv)
    client = WhfbAppClient()
    try:
        if args.command == "unit":
            ok = _import_unit(client, args.slug, args.army, args.data_dir, args.dry_run)
        else:
            ok = _import_army(client, args.slug, args.data_dir, args.dry_run)
    except WhfbAppError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0 if ok else 1


def _import_unit(
    client: WhfbAppClient, slug: str, army: str | None, data_dir: Path, dry_run: bool
) -> bool:
    entry = client.unit_entry(slug)
    if army is None:
        army = _resolve_army(client, entry)
        print(f"{slug}: army resolved to {army!r}", file=sys.stderr)
    return _write_unit(entry, army, data_dir, dry_run)


def _import_army(client: WhfbAppClient, army: str, data_dir: Path, dry_run: bool) -> bool:
    slugs = client.army_unit_slugs(army)
    if not slugs:
        print(f"error: army {army!r} lists no units", file=sys.stderr)
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
        print(f"{slug}: skipped ({err})", file=sys.stderr)
        return True
    except WhfbParseError as err:
        print(f"{slug}: FAILED ({err})", file=sys.stderr)
        return False
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    text = unit_to_yaml(result.unit, source_url=f"{BASE_URL}/unit/{slug}")
    if dry_run:
        print(text)
        return True
    path = data_dir / "tow" / "armies" / army / "units" / f"{slug}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    print(f"wrote {path}")
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
