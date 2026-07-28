"""What a re-import must not overwrite.

Some of what lives in ``data/`` is written by hand rather than scraped: a
rule's effects and the notes recording what the engine does with it, a
weapon's rulebook family. A page states none of that, so an import that
wrote only what it read would delete it. Every writer therefore reads the
existing file first and carries those fields across.

Which fields those are is declared per kind in :data:`HAND_AUTHORED`, and
a test holds it against each schema: a new field has to be classified as
scraped or hand-authored before it can be added, rather than being
silently dropped on the next re-import.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from avelorn.core.loading import load_yaml
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.weapon import Weapon

from .parse import WhfbParseError

# Per kind, the fields no page states. Everything else the importer owns
# and may overwrite. An armour page states all of its own.
HAND_AUTHORED: dict[type[BaseModel], frozenset[str]] = {
    Rule: frozenset({"effects", "notes"}),
    Weapon: frozenset({"weapon_type"}),
    Armour: frozenset(),
}


def with_hand_authored[T: BaseModel](fresh: T, path: Path) -> tuple[T, list[str]]:
    """Carry the hand-authored fields of an existing file into a re-import.

    If the existing file does not validate, refuse rather than clobber
    whatever a human wrote there. And because hand-authored fields are
    written against what the page said at the time, a re-import that
    changes any scraped field warns that they need re-verifying — the
    FAQ/errata reread case.

    Returns:
        The fresh entry carrying anything hand-authored the file held,
        and the warnings raised merging them.

    Raises:
        WhfbParseError: The existing file cannot be read as its own kind.
    """
    kind = type(fresh)
    fields = HAND_AUTHORED[kind]
    if not fields or not path.exists():
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
    changed = sorted(
        name
        for name in kind.model_fields
        if name not in fields and getattr(existing, name) != getattr(fresh, name)
    )
    warnings = []
    if changed:
        warnings.append(
            f"page changed ({', '.join(changed)}) since {', '.join(kept)} "
            f"{'was' if len(kept) == 1 else 'were'} written by hand; "
            "re-verify them against the new wording"
        )
    return fresh.model_copy(update=kept), warnings
