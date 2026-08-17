"""The CLI's commands: what each one reads out of the corpus.

Each command returns the lines to print rather than printing them, so what it
reports is what a test reads. The flags that reach these live in
:mod:`avelorn.cli.main`.
"""

import textwrap
from collections.abc import Sequence

import yaml

from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import BaseSize, Characteristic, Unit, UnitOption, UnitSize
from avelorn.tow.views import UnitSummary, rule_summaries, unmodelled_rules


def list_units(data: TOWRepository) -> list[str]:
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


def show_unit(data: TOWRepository, slug: str) -> list[str]:
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


def list_rules(data: TOWRepository) -> list[str]:
    """List every rule entry, and whether it reaches the maths.

    Returns:
        The lines to print.
    """
    rows = [["SLUG", "NAME", "CATEGORY", "FACTORS", "PRINTED BY"]]
    rows.extend(
        [
            summary.id,
            summary.name,
            summary.category or "-",
            "yes" if summary.factors else "no",
            str(summary.references),
        ]
        for summary in rule_summaries(data)
    )
    return _columns(rows)


def list_unmodelled(data: TOWRepository) -> list[str]:
    """Report every rule the corpus prints without an entry to apply.

    The same honesty the per-action "special rule not factored" notes give,
    totalled: what is printed, and who prints it.

    Returns:
        The lines to print.
    """
    report = unmodelled_rules(data)
    entries = len(rule_summaries(data))
    lines = [f"{len(report)} printed rules have no entry ({entries} entries in all):"]
    for rule in report:
        lines.extend(["", rule.name])
        if rule.units:
            lines.append(f"    units:   {', '.join(rule.units)}")
        if rule.weapons:
            lines.append(f"    weapons: {', '.join(rule.weapons)}")
    return lines


def show_rule(data: TOWRepository, slug: str) -> list[str]:
    """Print one rule entry: its text, its effects, and what it leaves out.

    Effects print as the YAML they are authored as, rather than a prose gloss --
    the file is the statement of what the engine does, so a second wording of it
    would only be something to drift.

    Returns:
        The lines to print.
    """
    rule = _rule(data, slug)
    page = "" if rule.page is None else f", page {rule.page}"
    lines = [f"{rule.name}  ({rule.id})", f"{rule.category or 'uncategorised'}{page}"]
    if rule.flavour:
        lines.extend(["", *(f"  {line}" for line in _wrapped(rule.flavour))])
    for paragraph in rule.paragraphs:
        lines.extend(["", *_wrapped(paragraph)])
    if rule.effects:
        dumped = yaml.safe_dump(
            [effect.model_dump(mode="json", exclude_none=True) for effect in rule.effects],
            sort_keys=False,
        )
        lines.extend(["", "Effects:", *(f"  {line}" for line in dumped.rstrip().splitlines())])
    else:
        lines.extend(["", "Effects: none -- the engine holds this text and does not apply it"])
    if rule.notes:
        lines.extend(["", "Not covered:", *(f"  {line}" for line in _wrapped(rule.notes))])
    return lines


def _rule(data: TOWRepository, slug: str) -> Rule:
    """Address a rule entry by slug.

    Returns:
        The rule entry.

    Raises:
        LookupError: no entry carries the slug. A rule the corpus prints without
            an entry is real but unreadable here, so the miss says where to look.
    """
    rule = data.rules.get(slug)
    if rule is None:
        raise LookupError(
            f"no rule entry {slug!r}; run `avelorn rules list` for the slugs, "
            "or `avelorn rules list --unmodelled` for the names printed without one"
        )
    return rule


def _wrapped(text: str, width: int = 96) -> list[str]:
    """Rule prose, wrapped to a readable width.

    Returns:
        The wrapped lines.
    """
    return textwrap.wrap(" ".join(text.split()), width=width) or [""]


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
        raise LookupError(f"no unit {slug!r}; run `avelorn units list` for the slugs")
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
