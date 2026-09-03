"""Merge the hand-authored layer back onto a freshly scraped entry.

Some of what lives in ``data/`` is written here rather than scraped, and
it comes in two kinds that a re-import has to treat differently.

**Fields the source never states** -- a rule's effects, an entry's
caveats, a weapon's rulebook family -- are carried across. Which
they are is declared per kind in :data:`HAND_AUTHORED`, and a test
holds it against each schema: a new field has to be classified as
scraped or hand-authored before it can be added, rather than being
silently dropped on the next re-import.

**Corrections** are the harder kind. They edit a field the importer
owns, so carrying them across is not enough -- they are reapplied to the
fresh scrape on every import, as RFC 6902 operations. Each is gated on
the value the source is stated to hold, so the day the source is fixed
the import stops rather than silently re-breaking the entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonpatch
import jsonpointer
import yaml
from pydantic import BaseModel, ValidationError

from avelorn.core.loading import load_yaml
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.correction import Correction
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon

from .parse import WhfbParseError

# Per kind, the fields no page states. Everything else the importer owns
# and may overwrite, and a correction may address. `caveats` is this
# project's on every kind; a weapon's and an armour's `notes` is the
# page's own prose, so a correction may address that.
HAND_AUTHORED: dict[type[BaseModel], frozenset[str]] = {
    Rule: frozenset({"effects", "caveats", "corrections"}),
    Unit: frozenset({"caveats", "corrections"}),
    Weapon: frozenset({"weapon_type", "caveats", "corrections"}),
    Armour: frozenset({"caveats", "corrections"}),
}


class StaleCorrection(WhfbParseError):
    """A correction no longer describes the source it corrects."""


def with_hand_authored[T: BaseModel](fresh: T, path: Path) -> tuple[T, list[str]]:
    """Carry an existing file's hand-authored fields onto a re-import.

    If the existing file does not validate, refuse rather than clobber
    whatever a human wrote there.

    Args:
        fresh: The entry as the source now states it.
        path: Where the entry is held, which may not exist yet.

    Returns:
        The fresh entry carrying what the file held, corrected, and the
        warnings raised merging them.

    Raises:
        WhfbParseError: The existing file cannot be read as its own kind.
    """
    kind = type(fresh)
    fields = HAND_AUTHORED[kind]
    if not path.exists():
        return fresh, []
    try:
        existing = load_yaml(path, kind)
    except (ValidationError, yaml.YAMLError) as err:
        raise WhfbParseError(
            f"{path}: existing file does not validate; refusing to overwrite: {err}"
        ) from err

    kept = {name: value for name in sorted(fields) if (value := getattr(existing, name))}
    if not kept:
        return fresh, []
    warnings = _reverification_warnings(kind, existing, fresh, kept)
    merged = fresh.model_copy(update=kept)
    if kept.get("corrections"):
        merged = _corrected(merged, kept["corrections"], path)
    return merged, warnings


def _reverification_warnings(
    kind: type[BaseModel], existing: BaseModel, fresh: BaseModel, kept: dict[str, Any]
) -> list[str]:
    """Warn about kept prose the source may have outgrown.

    Hand-authored prose is written against what the page said at the
    time, so a page that has since moved leaves it to re-verify -- the
    FAQ/errata reread case. A field under a correction is not counted as
    moved: the correction carries the value it expects the source to
    hold, so a page that moved under it fails the import outright rather
    than needing a human to notice.

    Returns:
        One warning naming what to re-verify, or nothing.
    """
    unverifiable = sorted(name for name in kept if name != "corrections")
    if not unverifiable:
        return []
    corrected = {c.path.split("/")[1] for c in kept.get("corrections", ())}
    changed = sorted(
        name
        for name in kind.model_fields
        if name not in HAND_AUTHORED[kind]
        and name not in corrected
        and getattr(existing, name) != getattr(fresh, name)
    )
    if not changed:
        return []
    return [
        f"page changed ({', '.join(changed)}) since {', '.join(unverifiable)} "
        f"{'was' if len(unverifiable) == 1 else 'were'} written by hand; "
        "re-verify them against the new wording"
    ]


def _corrected[T: BaseModel](entry: T, corrections: list[Correction], path: Path) -> T:
    """Apply the held corrections to the scraped entry.

    The hand-authored fields are lifted off first, so a correction
    addresses only what the source states and cannot reach its own reason
    for existing. Corrections apply in order, each seeing what the one
    before it left.

    Returns:
        The entry as this corpus states it.

    Raises:
        StaleCorrection: A correction's expectation of the source no
            longer holds, or its path addresses nothing.
    """
    document = entry.model_dump(mode="json")
    ours = {name: document.pop(name) for name in HAND_AUTHORED[type(entry)]}
    for correction in corrections:
        _refuse_stale(document, correction, path)
        try:
            document = jsonpatch.JsonPatch(_operations(correction)).apply(document)
        except jsonpatch.JsonPatchTestFailed as err:
            raise StaleCorrection(
                f"{path}: correction at {correction.path} expects "
                f"{correction.expect!r}, but the source now states "
                f"{jsonpointer.resolve_pointer(document, correction.path, None)!r}; "
                f"re-check it and drop the correction if the source has been "
                f"fixed ({correction.why})"
            ) from err
    return type(entry).model_validate(document | ours)


def _refuse_stale(document: dict, correction: Correction, path: Path) -> None:
    """Refuse a correction the source has outgrown, before the patch runs.

    Two ways it can be stale beyond a failed ``test``. Its path may
    address nothing, which for a gated operation ``test`` would report as
    a value mismatch against nothing -- true but useless. And ``add`` is
    the one operation RFC 6902 gives no precondition for, its ``expect``
    being "nothing", which ``test`` cannot say; an addition whose value
    the source already carries is as stale as a failed ``test``.

    Raises:
        StaleCorrection: The path addresses nothing, or the source
            already supplies what the correction adds.
    """
    pointer = jsonpointer.JsonPointer(correction.path)
    try:
        parent, key = pointer.to_last(document)
        if correction.op != "add":
            pointer.get(document)
    except jsonpointer.JsonPointerException as err:
        raise StaleCorrection(
            f"{path}: correction at {correction.path} addresses nothing in the "
            f"source, so it cannot be applied ({correction.why}): {err}"
        ) from err
    if correction.op != "add":
        return
    already = correction.value in parent if isinstance(parent, list) else key in parent
    if already:
        raise StaleCorrection(
            f"{path}: correction adds {correction.value!r} at {correction.path}, "
            f"but the source already states it; drop the correction ({correction.why})"
        )


def _operations(correction: Correction) -> list[dict[str, Any]]:
    """The RFC 6902 operations one correction compiles to.

    Returns:
        The gating ``test``, where the operation admits one, then the
        operation itself.
    """
    gate = [{"op": "test", "path": correction.path, "value": correction.expect}]
    if correction.op == "add":
        return [{"op": "add", "path": correction.path, "value": correction.value}]
    if correction.op == "remove":
        return [*gate, {"op": "remove", "path": correction.path}]
    return [*gate, {"op": "replace", "path": correction.path, "value": correction.value}]
