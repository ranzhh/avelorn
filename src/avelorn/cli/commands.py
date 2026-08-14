"""The CLI's commands: what each one reads out of the corpus.

Each command returns the lines to print rather than printing them, so what it
reports is what a test reads. The flags that reach these live in
:mod:`avelorn.cli.main`.
"""

from collections.abc import Sequence

from avelorn.tow.game import TOWGame
from avelorn.tow.schema.unit import Characteristic, Unit, UnitOption


def units(game: TOWGame) -> list[str]:
    """List every datasheet in the corpus: slug, name, cost, allowed size.

    Returns:
        The lines to print.
    """
    rows = [["SLUG", "NAME", "PTS/MODEL", "SIZE", "TROOP TYPE"]]
    rows.extend(
        [unit.id, unit.name, str(unit.points), _size(unit), unit.troop_type.value]
        for _, unit in sorted(game.units.items())
    )
    return _columns(rows)


def show(game: TOWGame, slug: str) -> list[str]:
    """Print one datasheet: its profile rows, cost, equipment, rules, and options.

    Returns:
        The lines to print.
    """
    unit = _unit(game, slug)
    rows = [["", *(characteristic.value for characteristic in Characteristic)]]
    rows.extend(
        [profile.name, *(_stat(profile[c]) for c in Characteristic)] for profile in unit.profiles
    )
    lines = [
        f"{unit.name}  ({unit.id})",
        f"{unit.troop_type.value}, {unit.points} points per model, unit size {_size(unit)}",
        "",
        *_columns(rows),
    ]
    lines.extend(_listing("Equipment", unit.equipment))
    lines.extend(_listing("Special rules", unit.special_rules))
    lines.extend(_listing("Options", [_option(option) for option in unit.options]))
    return lines


def _unit(game: TOWGame, slug: str) -> Unit:
    """Address a datasheet by slug.

    Returns:
        The datasheet.

    Raises:
        LookupError: no datasheet carries the slug. The registry raises a bare
            KeyError, which at a terminal reads as the slug and nothing else.
    """
    unit = game.units.get(slug)
    if unit is None:
        raise LookupError(f"no unit {slug!r}; run `avelorn units` for the slugs")
    return unit


def _size(unit: Unit) -> str:
    """A datasheet's allowed model count.

    Returns:
        The range, open-ended when the datasheet prints no maximum.
    """
    allowed = unit.unit_size
    return f"{allowed.min}+" if allowed.max is None else f"{allowed.min}-{allowed.max}"


def _stat(value: int | None) -> str:
    """One profile characteristic.

    Returns:
        The value, or the printed dash for one that does not apply.
    """
    return "-" if value is None else str(value)


def _option(option: UnitOption) -> str:
    """One purchasable option, with the cost shape it carries.

    Returns:
        The option's name and price.
    """
    if option.points is None:
        return f"{option.name} (up to {option.points_budget} points of magic items)"
    per = "/model" if option.per_model else ""
    plural = "" if option.points == 1 else "s"
    return f"{option.name} ({option.points} point{plural}{per})"


def _listing(heading: str, entries: list[str]) -> list[str]:
    """A named list, omitted entirely when it is empty.

    Returns:
        The heading and its indented entries, or nothing.
    """
    if not entries:
        return []
    return ["", f"{heading}:", *(f"  {entry}" for entry in entries)]


def _columns(rows: Sequence[Sequence[str]], *, gap: str = "  ") -> list[str]:
    """Left-aligned columns, each sized to its widest cell.

    Returns:
        One line per row, the trailing padding stripped.
    """
    if not rows:
        return []
    widths = [
        max(len(row[at]) if at < len(row) else 0 for row in rows) for at in range(len(rows[0]))
    ]
    padded = (gap.join(cell.ljust(widths[at]) for at, cell in enumerate(row)) for row in rows)
    return [line.rstrip() for line in padded]
