"""The CLI's commands: what each one reads out of the corpus.

Each command returns the lines to print rather than printing them, so what it
reports is what a test reads. The flags that reach these live in
:mod:`avelorn.cli.main`.
"""

from collections.abc import Sequence

from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.unit import BaseSize, Characteristic, Unit, UnitOption, UnitSize
from avelorn.tow.views import UnitSummary


def units(data: TOWRepository) -> list[str]:
    """List every datasheet in the corpus: slug, name, cost, allowed size.

    One column per field of the shared listing view, so the terminal shows
    exactly what ``GET /units`` serves.

    Returns:
        The lines to print.
    """
    rows = [["SLUG", "NAME", "PTS/MODEL", "SIZE", "TROOP TYPE"]]
    rows.extend(
        [
            summary.id,
            summary.name,
            str(summary.points),
            _size(summary.unit_size),
            summary.troop_type.value,
        ]
        for summary in (UnitSummary.of(unit) for _, unit in sorted(data.units.items()))
    )
    return _columns(rows)


def show(data: TOWRepository, slug: str) -> list[str]:
    """Print one datasheet whole -- everything ``GET /units/{slug}`` serves.

    The detail view is the datasheet itself, so every field
    :class:`~avelorn.tow.schema.unit.Unit` carries reaches the terminal; a test
    holds the two surfaces to that.

    Returns:
        The lines to print.
    """
    unit = _unit(data, slug)
    rows = [["", *(characteristic.value for characteristic in Characteristic)]]
    rows.extend(
        [profile.name, *(_stat(profile[c]) for c in Characteristic)] for profile in unit.profiles
    )
    lines = [
        f"{unit.name}  ({unit.id})",
        f"{unit.troop_type.value}, {unit.points} points per model, "
        f"unit size {_size(unit.unit_size)}",
        f"base {_base(unit.base_size)}, {_ranks(unit)}",
        "",
        *_columns(rows),
    ]
    lines.extend(_listing("Equipment", unit.equipment))
    lines.extend(_listing("Special rules", unit.special_rules))
    lines.extend(_listing("Options", [_option(option) for option in unit.options]))
    return lines


def _unit(data: TOWRepository, slug: str) -> Unit:
    """Address a datasheet by slug.

    Returns:
        The datasheet.

    Raises:
        LookupError: no datasheet carries the slug. The registry raises a bare
            KeyError, which at a terminal reads as the slug and nothing else.
    """
    unit = data.units.get(slug)
    if unit is None:
        raise LookupError(f"no unit {slug!r}; run `avelorn units` for the slugs")
    return unit


def _base(size: BaseSize | None) -> str:
    """A model's footprint, in millimetres.

    Returns:
        The printed WxD, or a dash where the datasheet gives none.
    """
    return "-" if size is None else f"{size.width_mm} x {size.depth_mm} mm"


def _ranks(unit: Unit) -> str:
    """How the unit's troop type ranks it up.

    Reads the profile the repository resolved onto the datasheet, which is what
    the engine consults for Unit Strength and rank bonus.

    Returns:
        The troop type's models per rank and rank-bonus cap, or a note that the
        profile is unresolved.
    """
    if unit.troop_type_profile is None:
        return "troop-type profile unresolved"
    profile = unit.troop_type_profile
    width = profile.models_per_rank
    per_rank = "any width" if width is None else f"{width}/rank"
    return f"{per_rank}, rank bonus up to +{profile.max_rank_bonus}"


def _size(size: UnitSize) -> str:
    """A datasheet's allowed model count.

    Returns:
        The range, open-ended when the datasheet prints no maximum.
    """
    return f"{size.min}+" if size.max is None else f"{size.min}-{size.max}"


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
