"""Canonicalise a fresh import's references against the corpus it joins.

The site spells its cross-references loosely: the Ceremonial Halberd's
page prints "Fight in Extra Rank" for the entry filed "Fight In Extra
Rank", and a replace-option gains prose "shortbows" for the Shortbow
entry. The engine resolves printed names exactly, on purpose — a corpus
that resolved loosely could never learn that two of its own files
disagree — so the looseness is absorbed at the one boundary where the
site's spelling enters the corpus: an import rewrites every reference
that matches an existing entry up to case or a trailing plural "s" to
the entry's own name, and reports each fix.

An equipment reference matching nothing is written as parsed — its entry
may simply not be imported yet — and the corpus-consistency test fails
loudly the moment both sides exist and still disagree, naming the
re-import that heals it. Rule references are slugs, resolved as they are
parsed (:mod:`~avelorn.tow.importers.whfb_app.references`), which uses
:func:`canonical` for the same looseness.
"""

from collections.abc import Iterable

from avelorn.tow.schema.unit import Unit


def canonical(reference: str, names: Iterable[str]) -> str | None:
    """The entry name ``reference`` spells loosely, if exactly one does.

    Loosely means up to case, or up to a trailing plural "s" on the
    reference (never on the entry, so a canonically plural name is only
    ever spelt as itself). An exact match is not loose, and a reference
    matching nothing is nobody's variant.

    Returns:
        The canonical name a re-import would write, or None when the
        reference is already exact or matches no entry.
    """
    index = {name.casefold(): name for name in names}
    folded = reference.casefold()
    found = index.get(folded)
    if found is None and folded.endswith("s"):
        found = index.get(folded[:-1])
    return found if found is not None and found != reference else None


def canonical_unit(unit: Unit, *, equipment: Iterable[str]) -> tuple[Unit, list[str]]:
    """This datasheet with its equipment references spelt as the corpus files them.

    The base list, each mount row's list and each option's adds and removes
    canonicalise against the weapon and armour names. Option display names
    stay as printed -- they are labels, not references. Rule references
    resolve as they are parsed (:mod:`~avelorn.tow.importers.whfb_app.references`).

    Returns:
        The rewritten datasheet and one report line per fix, empty when
        every reference was already canonical.
    """
    names = list(equipment)
    fixes: list[str] = []

    def fixed(references: list[str]) -> list[str]:
        rewritten = []
        for reference in references:
            found = canonical(reference, names)
            if found is not None:
                fixes.append(f"reference {reference!r} canonicalised to {found!r}")
            rewritten.append(found if found is not None else reference)
        return rewritten

    options = [
        option.model_copy(
            update={
                "adds_equipment": fixed(option.adds_equipment),
                "removes_equipment": fixed(option.removes_equipment),
            }
        )
        for option in unit.options
    ]
    profiles = [
        row.model_copy(update={"equipment": fixed(row.equipment)}) for row in unit.profiles
    ]
    rewritten = unit.model_copy(
        update={"equipment": fixed(unit.equipment), "profiles": profiles, "options": options}
    )
    return rewritten, fixes
