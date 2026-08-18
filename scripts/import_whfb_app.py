"""Import units, weapons, armour, and rules from tow.whfb.app into data/.

uv run python scripts/import_whfb_app.py unit elven-archers
uv run python scripts/import_whfb_app.py unit elven-archers --army high-elf-realms
uv run python scripts/import_whfb_app.py army high-elf-realms
uv run python scripts/import_whfb_app.py weapon longbow
uv run python scripts/import_whfb_app.py armour light-armour
uv run python scripts/import_whfb_app.py rule armour-bane

`check` re-imports what data/ already holds and reports which files a real
import would change, writing nothing — the site moved underneath them, or
the importer would not reproduce what is on disk:

uv run python scripts/import_whfb_app.py check
uv run python scripts/import_whfb_app.py check data/tow/armies/high-elf-realms
"""

from __future__ import annotations

import argparse
import difflib
import logging
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from avelorn.core.loading import load_yaml
from avelorn.core.logging import configure_logging
from avelorn.tow.data import TOWRepository
from avelorn.tow.importers.whfb_app.canon import canonical_unit, canonical_weapon
from avelorn.tow.importers.whfb_app.client import BASE_URL, WhfbAppClient, WhfbAppError
from avelorn.tow.importers.whfb_app.equipment import parse_armour, parse_weapon
from avelorn.tow.importers.whfb_app.parse import UnsupportedUnit, WhfbParseError, parse_unit
from avelorn.tow.importers.whfb_app.preserve import with_hand_authored
from avelorn.tow.importers.whfb_app.rules import parse_special_rule
from avelorn.tow.importers.whfb_app.yamlout import (
    armour_to_yaml,
    rule_to_yaml,
    unit_to_yaml,
    weapon_to_yaml,
)
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon

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

    check_cmd = sub.add_parser("check", help="report which data/ files a re-import would change")
    check_cmd.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="files or directories to check; the whole data/ tree by default",
    )
    check_cmd.add_argument("--data-dir", type=Path, default=Path("data"))

    args = parser.parse_args(argv)
    configure_logging()
    client = WhfbAppClient()
    try:
        if args.command == "check":
            ok = _check(client, args.paths or [args.data_dir], data_dir=args.data_dir)
        elif args.command == "unit":
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


# Every generated file opens with the page it came from, so a file knows
# where to re-read itself — including a rule whose page lives outside the
# Special Rules chapter, whose path the flat filename does not record.
_SOURCE_RE = re.compile(r"\A# Source: (\S+)")


def _corpus_names(data_dir: Path) -> tuple[set[str], set[str]]:
    """The canonical names an import's references are spelt against.

    Loaded fresh from ``data_dir`` so an import canonicalises against the
    corpus as it stands — including whatever this run already wrote.

    Returns:
        The equipment names (weapons and armour together) and the rule
        entry names.
    """
    corpus = TOWRepository(data_dir=data_dir)
    equipment = {item.name for item in (*corpus.weapons.values(), *corpus.armoury.values())}
    rules = {rule.name for rule in corpus.rules.values()}
    return equipment, rules


def _data_files(paths: Sequence[Path]) -> list[Path]:
    """Expand the requested paths into the YAML files under them.

    Returns:
        Every named file, plus every ``.yaml`` under every named directory.
    """
    files: list[Path] = []
    for path in paths:
        files.extend([path] if path.is_file() else sorted(path.rglob("*.yaml")))
    return files


def _rerender(
    client: WhfbAppClient, path: Path, url: str, *, data_dir: Path
) -> tuple[str, str, list[str]] | None:
    """Render one data file both as held and as the site now states it.

    The kind comes from where the file sits in the tree, and the page from
    the file's own source header — so no slug is guessed and, unlike an
    import, no army has to be resolved.

    Both sides go through the same renderer, so the comparison is of what
    the importer owns. Line wrapping, hand-authored comments and any field
    the importer does not write cancel out instead of reading as drift.

    Returns:
        The held YAML, the site's YAML, and the warnings raised reading
        the page — or None for a file whose kind no importer covers (the
        troop-type table cites its page but is written by hand).
    """
    kind = path.parent.name
    slug = url.rsplit("/", 1)[-1]
    if kind == "units":
        result = parse_unit(client.unit_entry(slug))
        equipment, rules = _corpus_names(data_dir)
        unit, fixes = canonical_unit(result.unit, equipment=equipment, rules=rules)
        held = unit_to_yaml(load_yaml(path, Unit), source_url=url)
        return held, unit_to_yaml(unit, source_url=url), [*result.warnings, *fixes]
    if kind == "weapons":
        result = parse_weapon(client.weapons_of_war_entry(slug))
        _, rules = _corpus_names(data_dir)
        fresh, fixes = canonical_weapon(result.weapon, rules=rules)
        weapon, merge_warnings = with_hand_authored(fresh, path)
        held = weapon_to_yaml(load_yaml(path, Weapon), source_url=url)
        return (
            held,
            weapon_to_yaml(weapon, source_url=url),
            [*result.warnings, *fixes, *merge_warnings],
        )
    if kind == "armour":
        armour = parse_armour(client.weapons_of_war_entry(slug))
        held = armour_to_yaml(load_yaml(path, Armour), source_url=url)
        return held, armour_to_yaml(armour.armour, source_url=url), armour.warnings
    if kind in ("rules", "magic-items"):
        # An army's magic items (tow/armies/<army>/magic-items/) re-render
        # through the rule path: their pages parse as rule entries, and the
        # source header already carries the full magic-item/<slug> path.
        result = parse_special_rule(client.rule_entry(url.removeprefix(f"{BASE_URL}/")))
        # Merged exactly as a real import would merge, so what the check
        # reports is what running the import would do.
        rule, merge_warnings = with_hand_authored(result.rule, path)
        held = rule_to_yaml(load_yaml(path, Rule), source_url=url)
        return held, rule_to_yaml(rule, source_url=url), [*result.warnings, *merge_warnings]
    return None


def _check(client: WhfbAppClient, paths: Sequence[Path], *, data_dir: Path) -> bool:
    """Report which files a re-import would change, writing nothing.

    Each file is re-imported into memory and compared with what is on
    disk. Files this importer does not generate are left alone: one with
    no source header, and one whose kind no importer covers.

    Hand-authored fields are merged exactly as an import merges them, so
    a difference is what running the import would actually do to the
    file. A page that no longer answers counts too: the entry moved or
    went away, which is what a stale corpus looks like.

    Returns:
        Whether every file checked would survive a re-import unchanged.
    """
    checked = 0
    skipped = 0
    drifted: list[Path] = []
    unreadable: list[Path] = []
    for path in _data_files(paths):
        current = path.read_text()
        source = _SOURCE_RE.match(current)
        if source is None:
            skipped += 1
            continue
        url = source.group(1)
        try:
            rendered = _rerender(client, path, url, data_dir=data_dir)
        except (WhfbAppError, WhfbParseError, UnsupportedUnit) as err:
            # A finding, not a crash: one line rather than a traceback, since
            # on a sweep the file and the reason are the whole report. The
            # summary and the exit code carry how much it matters.
            logger.warning("%s: %s", path, err)
            unreadable.append(path)
            continue
        if rendered is None:
            skipped += 1
            continue
        held, fresh, warnings = rendered
        checked += 1
        if fresh == held:
            continue
        drifted.append(path)
        for warning in warnings:
            logger.warning("%s: %s", path.name, warning)
        # The diff is the payload -> stdout, like the generated YAML.
        print(
            "".join(
                difflib.unified_diff(
                    held.splitlines(keepends=True),
                    fresh.splitlines(keepends=True),
                    fromfile=f"{path} (held)",
                    tofile=f"{url} (site)",
                )
            ),
            end="",
        )
    logger.info(
        "checked %d file(s): %d would change, %d unreadable, %d not imported from the site",
        checked,
        len(drifted),
        len(unreadable),
        skipped,
    )
    for path in drifted:
        logger.info("would change: %s", path)
    return not drifted and not unreadable


def _import_equipment(
    client: WhfbAppClient, kind: str, slug: str, data_dir: Path, dry_run: bool
) -> bool:
    entry = client.weapons_of_war_entry(slug)
    subdir = "weapons" if kind == "weapon" else "armour"
    path = data_dir / "tow" / subdir / f"{slug}.yaml"
    url = f"{BASE_URL}/weapons-of-war/{slug}"
    try:
        if kind == "weapon":
            result = parse_weapon(entry)
            _, rules = _corpus_names(data_dir)
            fresh, fixes = canonical_weapon(result.weapon, rules=rules)
            for fix in fixes:
                logger.info("%s: %s", slug, fix)
            weapon, merge_warnings = with_hand_authored(fresh, path)
            text = weapon_to_yaml(weapon, source_url=url)
        else:
            result = parse_armour(entry)
            armour, merge_warnings = with_hand_authored(result.armour, path)
            text = armour_to_yaml(armour, source_url=url)
    except WhfbParseError:
        logger.exception("%s: parse failed", slug)
        return False
    for warning in (*result.warnings, *merge_warnings):
        logger.warning("%s: %s", slug, warning)
    if dry_run:
        print(text)  # generated YAML is the program's payload -> stdout
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    logger.info("wrote %s", path)
    return True


def _import_rule(client: WhfbAppClient, slug: str, data_dir: Path, dry_run: bool) -> bool:
    entry = client.rule_entry(slug)
    # The file is named by the rule's own slug; a chapter-page path like
    # "the-shooting-phase/firing-at-long-range" still lands flat in rules/.
    try:
        result = parse_special_rule(entry)
        path = data_dir / "tow" / "rules" / f"{result.rule.id}.yaml"
        rule, merge_warnings = with_hand_authored(result.rule, path)
    except WhfbParseError:
        logger.exception("%s: import failed", slug)
        return False
    for warning in (*result.warnings, *merge_warnings):
        logger.warning("%s: %s", slug, warning)
    if rule.effects:
        logger.info("%s: preserved %d hand-authored effect(s)", slug, len(rule.effects))
    page_path = slug if "/" in slug else f"special-rules/{slug}"
    text = rule_to_yaml(rule, source_url=f"{BASE_URL}/{page_path}")
    if dry_run:
        print(text)  # generated YAML is the program's payload -> stdout
        return True
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
    equipment, rules = _corpus_names(data_dir)
    unit, fixes = canonical_unit(result.unit, equipment=equipment, rules=rules)
    for fix in fixes:
        logger.info("%s: %s", slug, fix)
    text = unit_to_yaml(unit, source_url=f"{BASE_URL}/unit/{slug}")
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
