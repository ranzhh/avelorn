"""Map a whfb.app `armyListEntry` payload onto the unit schema.

The importer never guesses silently: a required field that does not match
a known pattern raises `WhfbParseError`, and an option line that matches no
known grammar comes through verbatim as `kind: other` with a warning, so
the human reviewing the generated YAML sees exactly what was not
understood.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import ValidationError

from avelorn.tow.schema.unit import (
    BaseSize,
    OptionKind,
    Profile,
    TroopType,
    Unit,
    UnitOption,
    UnitSize,
)

from . import richtext
from .richtext import Node, OptionLine

_STAT_KEYS = ("M", "WS", "BS", "S", "T", "W", "I", "A", "Ld")

# Troop types the unit schema cannot represent yet.
_UNSUPPORTED_TROOP_TYPES = {"Character", "Named Character"}


class WhfbParseError(Exception):
    """A required field could not be understood."""


class UnsupportedUnit(Exception):
    """The entry is real but outside what the unit schema models yet."""


@dataclass
class ImportResult:
    """A parsed unit plus everything the parser was unsure about."""

    unit: Unit
    warnings: list[str]


def parse_unit(entry: Node) -> ImportResult:
    """Parse a whfb.app `armyListEntry` into a Unit.

    Returns:
        The unit and the warnings raised while mapping it.

    Raises:
        WhfbParseError: A required field is missing or unparseable.
    """
    fields = entry.get("fields", {})
    slug = fields.get("slug")
    if not slug:
        raise WhfbParseError("entry has no slug")
    warnings: list[str] = []

    # The options grammar reads a line's subject against the printed
    # profiles, so the rows are parsed before the options that name them.
    profiles = _parse_profiles(slug, _require(fields, slug, "unitProfile", list))

    unit = Unit(
        id=slug,
        name=_require(fields, slug, "name", str),
        points=_require(fields, slug, "cost", int),
        unit_size=_parse_unit_size(slug, _require(fields, slug, "unitSize", object)),
        troop_type=_parse_troop_type(slug, fields, warnings),
        base_size=_parse_base_size(slug, fields.get("baseSize"), warnings),
        profiles=profiles,
        # Equipment is prose, so display text is unusable ("thrusting
        # spears"): use canonical entry names. The special-rules field is a
        # bare list whose display text is the rule name as printed, which
        # can differ from the linked entry ("Detachment" links to the
        # "Detachment Special Rules" section).
        equipment=_rule_list(slug, "equipment", fields, warnings),
        special_rules=_rule_list(slug, "specialRules", fields, warnings, as_displayed=True),
        options=_parse_options(slug, fields.get("options"), profiles, warnings),
    )
    return ImportResult(unit=unit, warnings=warnings)


def _require[T](fields: Node, slug: str, key: str, kind: type[T]) -> T:
    value = fields.get(key)
    if not isinstance(value, kind):
        raise WhfbParseError(f"{slug}: missing or invalid required field {key!r}")
    return value


def _parse_unit_size(slug: str, raw: object) -> UnitSize:
    text = str(raw).strip()
    if m := re.fullmatch(r"(\d+)\+", text):
        return UnitSize(min=int(m.group(1)))
    # the dash class covers both hyphen and en dash range separators
    if m := re.fullmatch(r"(\d+)\s*[-\u2013]\s*(\d+)", text):
        return UnitSize(min=int(m.group(1)), max=int(m.group(2)))
    if m := re.fullmatch(r"\d+", text):
        return UnitSize(min=int(text), max=int(text))
    raise WhfbParseError(f"{slug}: cannot parse unit size {raw!r}")


def _parse_troop_type(slug: str, fields: Node, warnings: list[str]) -> TroopType:
    names = [t["fields"]["name"] for t in fields.get("troopType", [])]
    unsupported = [n for n in names if n in _UNSUPPORTED_TROOP_TYPES]
    if unsupported:
        raise UnsupportedUnit(
            f"{slug}: troop type {unsupported[0]!r} is not in the unit schema yet"
        )
    try:
        types = [TroopType(n) for n in names]
    except ValueError:
        raise WhfbParseError(f"{slug}: unknown troop type(s) {names!r}") from None
    if not types:
        raise WhfbParseError(f"{slug}: no troop type")
    if len(types) > 1:
        warnings.append(f"{slug}: multiple troop types {names!r}; keeping {names[0]!r}")
    return types[0]


_BASE_SIZE_RE = re.compile(r"(\d+)\s*x\s*(\d+)\s*mm")


def _parse_base_size(slug: str, raw: object, warnings: list[str]) -> BaseSize | None:
    if raw is None:
        return None
    if m := _BASE_SIZE_RE.fullmatch(str(raw).strip()):
        return BaseSize(width_mm=int(m.group(1)), depth_mm=int(m.group(2)))
    # e.g. war machines: "50 x 50 mm (war machine), 25 x 25 mm (crew)" —
    # the schema holds a single base size, so leave it for the human.
    warnings.append(f"{slug}: base size {str(raw)!r} is not a single WxD value; left unset")
    return None


def _parse_profiles(slug: str, raw_profiles: object) -> list[Profile]:
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise WhfbParseError(f"{slug}: unitProfile is empty")
    profiles = []
    for row in raw_profiles:
        if not isinstance(row, dict):
            raise WhfbParseError(f"{slug}: malformed profile row {row!r}")
        data = {"name": row.get("Name", "")} | {k: row.get(k, "-") for k in _STAT_KEYS}
        profiles.append(Profile.model_validate(data))
    return profiles


def _slugified(text: str) -> str:
    """Slugify a name the way the site builds entry slugs.

    Returns:
        Lowercase text with non-alphanumeric runs collapsed to hyphens.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _rule_list(
    slug: str, key: str, fields: Node, warnings: list[str], as_displayed: bool = False
) -> list[str]:
    """Collect a rich-text field's linked rule names.

    Verifies that the visible text contains nothing beyond those links and
    separators.

    Returns:
        The linked names, in document order.
    """
    doc = fields.get(key)
    if doc is None:
        return []
    names = richtext.linked_rule_names(doc, as_displayed=as_displayed)
    if not as_displayed:
        # A benign display text merely extends the entry name: a plural
        # "s" or trailing words ("thrusting spears" vs "Thrusting Spear").
        # One that does not start with the name points at a broader rules
        # page ("Repeater bolt thrower" -> "Bolt Throwers") and deserves a
        # human look.
        for display, name in richtext.linked_rules(doc):
            if display and not _slugified(display).startswith(_slugified(name)):
                warnings.append(
                    f"{slug}: {key} displayed as {display!r} "
                    f"but linked entry is {name!r}; kept {name!r}"
                )
    leftover = richtext.text_of(doc, links_as_names=not as_displayed)
    for name in names:
        leftover = leftover.replace(name, "", 1)
    leftover = re.sub(r"[\s,]|\band\b", "", leftover)
    if leftover:
        warnings.append(f"{slug}: {key} has text not covered by linked rules: {leftover!r}")
    return names


# --- options grammar ---------------------------------------------------

# A printed cost is "+N points", optionally bracketed and optionally
# scoped. The scope is omitted where only one model can take the option
# ("Brace of Drakefire Pistols (+10 points)"), so an unscoped cost is a
# one-off, the same shape as "per unit".
_COST_BODY = r"\+(?P<points>[\d,]+)\s+points?(?:\s+per\s+(?P<scope>unit|model))?"
_COST_RES = (
    re.compile(rf"\s*\({_COST_BODY}\)$", re.I),
    re.compile(rf"\s*{_COST_BODY}$", re.I),
)
# A page cross-reference, not part of the printed name: "Drakegun (see below)".
_CROSS_REF_RE = re.compile(r"\s*\(see\s+[^)]+\)", re.I)
# A line or group header reads "<subject> may ...". A header may also carry
# the verb its children omit: "The entire unit may take any of the following:".
_HEADER_RE = re.compile(
    r"^(?P<subject>.+?)\s+may"
    r"(?:\s+(?P<verb>.+?)\s+(?P<quantifier>any|one)\s+of the following)?:?$",
    re.I,
)
_LINE_SUBJECT_RE = re.compile(r"^(?P<subject>.+?)\s+may\s+(?P<body>.+)$", re.I)
_SUBJECT_PLAIN_RE = re.compile(r"^(?:Any|The entire)\s+units?(?:\s+of\s+.+?)?$", re.I)
_SUBJECT_LIMIT_RE = re.compile(
    r"^(\d+-\d+)\s+units?(?:\s+of\s+.+?)?\s+per\s+([\d,]+)\s+points$", re.I
)
_SUBJECT_MODEL_RE = re.compile(r"^an?\s+(.+)$", re.I)
_UPGRADE_RE = re.compile(r"^upgrade one model to an?\s+(.+)$", re.I)
_RULE_ADD_RE = re.compile(r"^have the\s+(.+?)\s+special rule$", re.I)
_RULE_SWAP_RE = re.compile(r"^replace the\s+(.+?)\s+special rule with\s+(.+)$", re.I)
_TAKE_RE = re.compile(r"^take\s+(.+)$", re.I)
# The possessive belongs to the sentence, not to the equipment's name:
# "replace their Shield with ..." removes "Shield".
_EQUIP_SWAP_RE = re.compile(r"^replace\s+(?:their|its|his|her)?\s*(.+?)\s+with\s+(.+)$", re.I)
_MAGIC_STANDARD_RE = re.compile(
    r"^purchase a magic standard worth up to\s+([\d,]+)\s+points$", re.I
)
_MAGIC_ITEMS_RE = re.compile(
    r"^an?\s+(.+?)\s+may purchase magic items up to a total of\s+([\d,]+)\s+points$", re.I
)


@dataclass
class OptionGroup:
    """What a group header says about the option lines nested under it.

    Attributes:
        limit: The availability restriction the header states, if any.
        applies_to: The model the header names, when the options belong to
            one model rather than the unit ("An Ironbeard may ...").
        verb: The verb the header carries on its children's behalf, for a
            header that states the action once ("The entire unit may take
            any of the following:") and leaves each child a bare name.
    """

    limit: str | None = None
    applies_to: str | None = None
    verb: str | None = None


def _parse_options(
    slug: str, doc: Node | None, profiles: list[Profile], warnings: list[str]
) -> list[UnitOption]:
    if doc is None:
        return []
    # An option's subject is only read as a model when the unit prints that
    # model's profile, so "An Ironbeard may ..." resolves against the
    # datasheet rather than on the shape of the words.
    printed = {profile.name for profile in profiles}
    options: list[UnitOption] = []
    for header, children in richtext.option_lines(doc):
        if not children:
            _append_option(options, slug, header, OptionGroup(), printed, warnings)
            continue
        group = _parse_group(slug, header.text, printed, warnings)
        for child in children:
            _append_option(options, slug, child, group, printed, warnings)
    return options


def _append_option(
    options: list[UnitOption],
    slug: str,
    line: OptionLine,
    group: OptionGroup,
    printed: set[str],
    warnings: list[str],
) -> None:
    try:
        options.append(_parse_option_line(slug, line, group, printed, warnings))
    except ValidationError:
        # e.g. a verbatim-fallback line with no parseable cost, which the
        # schema's points-xor-budget rule rejects. Dropping it silently
        # would hide source data, so say exactly what is missing.
        warnings.append(f"{slug}: option not representable by the schema, DROPPED: {line.text!r}")


def _parse_subject(subject: str, printed: set[str]) -> OptionGroup | None:
    """Read who an option line or group header is about.

    Returns:
        The restriction or model the subject names, or None when the
        subject is outside the grammar.
    """
    if _SUBJECT_PLAIN_RE.fullmatch(subject):
        return OptionGroup()
    if m := _SUBJECT_LIMIT_RE.fullmatch(subject):
        return OptionGroup(limit=f"{m.group(1)} unit per {m.group(2).replace(',', '')} points")
    if (m := _SUBJECT_MODEL_RE.fullmatch(subject)) and m.group(1) in printed:
        return OptionGroup(applies_to=m.group(1))
    return None


def _parse_group(slug: str, header: str, printed: set[str], warnings: list[str]) -> OptionGroup:
    """Read a group header into what it says about its children.

    Returns:
        The header's restriction, the model it names, and the verb it
        carries for its children. An unrecognised header is kept verbatim
        as the limit rather than dropped.
    """
    if (m := _HEADER_RE.fullmatch(header)) and (
        group := _parse_subject(m.group("subject"), printed)
    ) is not None:
        if (m.group("quantifier") or "").lower() == "one":
            warnings.append(
                f"{slug}: options under {header!r} are mutually exclusive; "
                "exclusivity not recorded"
            )
        group.verb = m.group("verb")
        return group
    # Unrecognised restriction: keep it verbatim rather than dropping it.
    warnings.append(f"{slug}: unrecognised option group header {header!r}; kept as limit")
    return OptionGroup(limit=header)


def _int(raw: str) -> int:
    return int(raw.replace(",", ""))


def _capitalized(name: str) -> str:
    return name[:1].upper() + name[1:]


def _parse_option_line(
    slug: str, line: OptionLine, group: OptionGroup, printed: set[str], warnings: list[str]
) -> UnitOption:
    text = line.text
    if text.endswith(" Or:"):
        # Mutually exclusive alternatives; the schema cannot express that yet.
        text = text.removesuffix(" Or:")
        warnings.append(
            f"{slug}: option {text!r} is part of an either/or choice; exclusivity not recorded"
        )

    points: int | None = None
    per_model = False
    for pattern in _COST_RES:
        if m := pattern.search(text):
            points = _int(m.group("points"))
            per_model = m.group("scope") == "model"
            text = text[: m.start()].strip()
            break
    text = _CROSS_REF_RE.sub("", text).strip()

    if m := _MAGIC_ITEMS_RE.fullmatch(text):
        return UnitOption(
            name=f"{_capitalized(m.group(1))} magic items",
            kind=OptionKind.OTHER,
            points_budget=_int(m.group(2)),
            limit=group.limit,
        )

    # A line may state its own subject ("An Ironbeard may take ...", "0-1
    # units per 1,000 points may ..."); otherwise it inherits the group's.
    body, scope = text, group
    if (m := _LINE_SUBJECT_RE.fullmatch(text)) and (
        stated := _parse_subject(m.group("subject"), printed)
    ) is not None:
        body = m.group("body")
        # What the line states about itself wins; what it leaves unsaid
        # still comes from the group it sits under.
        scope = OptionGroup(
            limit=stated.limit or group.limit,
            applies_to=stated.applies_to or group.applies_to,
        )

    option = _matched_option(slug, body, points, per_model, scope, warnings)
    if option is None and group.verb:
        # The header stated the action for the whole group, so this line is
        # a bare name: "take" + "Great Weapon".
        option = _matched_option(slug, f"{group.verb} {body}", points, per_model, scope, warnings)
    if option is not None:
        return option

    warnings.append(f"{slug}: option line not understood, kept verbatim: {line.text!r}")
    return UnitOption(
        name=text,
        kind=OptionKind.OTHER,
        applies_to=scope.applies_to,
        points=points,
        per_model=per_model,
        limit=scope.limit,
    )


def _matched_option(
    slug: str,
    body: str,
    points: int | None,
    per_model: bool,
    scope: OptionGroup,
    warnings: list[str],
) -> UnitOption | None:
    """Match one option line against the printed forms the grammar knows.

    Returns:
        The option, or None when the line matches no printed form.
    """
    if m := _MAGIC_STANDARD_RE.fullmatch(body):
        return UnitOption(
            name="Magic standard",
            kind=OptionKind.MAGIC_STANDARD,
            points_budget=_int(m.group(1)),
            applies_to=scope.applies_to,
            limit=scope.limit,
        )
    if m := _UPGRADE_RE.fullmatch(body):
        return _upgrade_option(slug, m.group(1), points, per_model, scope, warnings)
    if m := _RULE_SWAP_RE.fullmatch(body):
        return UnitOption(
            name=m.group(2),
            kind=OptionKind.SPECIAL_RULE,
            points=points,
            per_model=per_model,
            adds_rules=[m.group(2)],
            removes_rules=[m.group(1)],
            applies_to=scope.applies_to,
            limit=scope.limit,
        )
    if m := _RULE_ADD_RE.fullmatch(body):
        return UnitOption(
            name=m.group(1),
            kind=OptionKind.SPECIAL_RULE,
            points=points,
            per_model=per_model,
            adds_rules=[m.group(1)],
            applies_to=scope.applies_to,
            limit=scope.limit,
        )
    if m := _TAKE_RE.fullmatch(body):
        return UnitOption(
            name=m.group(1),
            kind=OptionKind.EQUIPMENT,
            points=points,
            per_model=per_model,
            adds_equipment=[m.group(1)],
            applies_to=scope.applies_to,
            limit=scope.limit,
        )
    if m := _EQUIP_SWAP_RE.fullmatch(body):
        # The gained side is often plain text rather than a rule link
        # ("Replace Cavalry Spear with shortbows"), so its name may not be
        # the canonical entry name; the YAML reviewer sees it either way.
        gained = _capitalized(m.group(2))
        return UnitOption(
            name=gained,
            kind=OptionKind.EQUIPMENT,
            points=points,
            per_model=per_model,
            adds_equipment=[gained],
            removes_equipment=[m.group(1)],
            applies_to=scope.applies_to,
            limit=scope.limit,
        )
    return None


def _upgrade_option(
    slug: str,
    raw_name: str,
    points: int | None,
    per_model: bool,
    scope: OptionGroup,
    warnings: list[str],
) -> UnitOption:
    name = raw_name
    kind: OptionKind | None = None
    if m := re.fullmatch(r"(.+?)\s*\(champion\)", name, re.I):
        name = m.group(1)
        kind = OptionKind.CHAMPION
    elif name.lower() == "standard bearer":
        # The source prose is lowercase; use the printed name as-is.
        name = "Standard Bearer"
        kind = OptionKind.STANDARD_BEARER
    elif name.lower() == "musician":
        kind = OptionKind.MUSICIAN
    if kind is None:
        warnings.append(
            f"{slug}: upgrade target {raw_name!r} has no known role; kind set to other"
        )
        kind = OptionKind.OTHER
    return UnitOption(
        name=_capitalized(name),
        kind=kind,
        applies_to=scope.applies_to,
        points=points,
        per_model=per_model,
        limit=scope.limit,
    )
