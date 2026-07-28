"""Options-grammar and printed-form parsing tests for the whfb.app importer.

The grammar's inputs are one-line printed forms, so the tests feed those
strings directly — no fixture payloads.
"""

import pytest

from avelorn.tow.importers.whfb_app.parse import (
    OptionGroup,
    UnsupportedUnit,
    WhfbParseError,
    _append_option,
    _parse_base_size,
    _parse_group,
    _parse_option_line,
    _parse_troop_type,
    _parse_unit_size,
    _slugified,
)
from avelorn.tow.importers.whfb_app.richtext import OptionLine
from avelorn.tow.schema.unit import BaseSize, OptionKind, TroopType, UnitOption, UnitSize


def _line(text: str) -> OptionLine:
    return OptionLine(text=text, rules=[])


def _option(
    text: str, group: OptionGroup | None = None, printed: set[str] | None = None
) -> tuple[UnitOption, list[str]]:
    warnings: list[str] = []
    option = _parse_option_line(
        "some-unit", _line(text), group or OptionGroup(), printed or set(), warnings
    )
    return option, warnings


def _group(header: str, printed: set[str] | None = None) -> tuple[OptionGroup, list[str]]:
    warnings: list[str] = []
    return _parse_group("some-unit", header, printed or set(), warnings), warnings


# --- printed scalar fields ----------------------------------------------


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("5+", UnitSize(min=5)),
        ("10-20", UnitSize(min=10, max=20)),
        ("10\u201320", UnitSize(min=10, max=20)),  # en dash separator
        ("1", UnitSize(min=1, max=1)),
    ],
)
def test_unit_size_parses_printed_forms(printed: str, expected: UnitSize) -> None:
    """Unit size accepts the open, ranged, and fixed printed forms."""
    assert _parse_unit_size("some-unit", printed) == expected


@pytest.mark.parametrize("printed", ["a few", "5-", "+5"])
def test_unit_size_rejects_unknown_forms(printed: str) -> None:
    """Anything outside the printed grammar is an error, not a guess."""
    with pytest.raises(WhfbParseError, match="unit size"):
        _parse_unit_size("some-unit", printed)


@pytest.mark.parametrize(
    ("text", "slug"),
    [("Silver Helms", "silver-helms"), ("N'kari's Chosen", "n-kari-s-chosen")],
)
def test_slugified_matches_site_slugs(text: str, slug: str) -> None:
    """Slugs lowercase the name and collapse non-alphanumeric runs."""
    assert _slugified(text) == slug


def test_base_size_parses_a_single_footprint() -> None:
    """A plain WxD value maps onto the schema."""
    warnings: list[str] = []
    assert _parse_base_size("some-unit", "25 x 25 mm", warnings) == BaseSize(
        width_mm=25, depth_mm=25
    )
    assert warnings == []


def test_base_size_leaves_multi_value_unset_with_warning() -> None:
    """A war-machine style double footprint is left for the human."""
    warnings: list[str] = []
    raw = "50 x 50 mm (war machine), 25 x 25 mm (crew)"
    assert _parse_base_size("some-unit", raw, warnings) is None
    assert any("left unset" in w for w in warnings)


def _troop_fields(*names: str) -> dict:
    return {"troopType": [{"fields": {"name": name}} for name in names]}


def test_troop_type_maps_the_printed_name() -> None:
    """A known troop type maps onto the closed enum."""
    warnings: list[str] = []
    parsed = _parse_troop_type("some-unit", _troop_fields("Regular Infantry"), warnings)
    assert parsed is TroopType.REGULAR_INFANTRY
    assert warnings == []


def test_troop_type_character_is_unsupported_not_an_error() -> None:
    """Characters are real units the schema cannot hold yet: skip, not fail."""
    with pytest.raises(UnsupportedUnit, match="Character"):
        _parse_troop_type("some-unit", _troop_fields("Character"), [])


def test_troop_type_unknown_name_raises() -> None:
    """A troop type outside the rulebook table is a parse error."""
    with pytest.raises(WhfbParseError, match="unknown troop type"):
        _parse_troop_type("some-unit", _troop_fields("Irregular Infantry"), [])


def test_troop_type_multiple_keeps_first_with_warning() -> None:
    """A multi-type unit collapses to the first, visibly."""
    warnings: list[str] = []
    fields = _troop_fields("Heavy Cavalry", "Light Cavalry")
    assert _parse_troop_type("some-unit", fields, warnings) is TroopType.HEAVY_CAVALRY
    assert any("multiple troop types" in w for w in warnings)


# --- option group headers -------------------------------------------------


def test_plain_group_header_carries_no_limit() -> None:
    """The "Any unit may:" header restricts nothing."""
    group, warnings = _group("Any unit may:")
    assert group == OptionGroup()
    assert warnings == []


def test_limited_group_header_becomes_a_limit_string() -> None:
    """A "0-1 units per 1,000 points may:" header normalises into the limit."""
    group, warnings = _group("0-1 units per 1,000 points may:")
    assert group == OptionGroup(limit="0-1 unit per 1000 points")
    assert warnings == []


def test_unrecognised_group_header_is_kept_verbatim() -> None:
    """An unknown restriction is preserved as the limit, with a warning."""
    header = "Units joined by a character may:"
    group, warnings = _group(header)
    assert group == OptionGroup(limit=header)
    assert any("unrecognised option group header" in w for w in warnings)


def test_group_header_verb_is_not_a_limit() -> None:
    """A header stating the action once yields a verb, not a restriction."""
    group, warnings = _group("The entire unit may take any of the following:")
    assert group == OptionGroup(limit=None, verb="take")
    assert warnings == []


def test_group_header_carries_both_a_limit_and_a_verb() -> None:
    """The restriction and the verb are read from the same header."""
    group, _ = _group("0-1 units per 1,000 points may take any of the following:")
    assert group == OptionGroup(limit="0-1 unit per 1000 points", verb="take")


def test_exclusive_group_header_warns_about_lost_exclusivity() -> None:
    """A "one of the following" group is a choice the schema cannot express yet."""
    group, warnings = _group("The entire unit may take one of the following:")
    assert group.verb == "take"
    assert any("mutually exclusive" in w for w in warnings)


# --- option lines under a verb-carrying header ------------------------------


def test_bare_line_takes_the_verb_from_its_header() -> None:
    """A child line that is only a name is read through the group's verb."""
    option, warnings = _option("Great Weapon (+1 point per model)", OptionGroup(verb="take"))
    assert option == UnitOption(
        name="Great Weapon",
        kind=OptionKind.EQUIPMENT,
        points=1,
        per_model=True,
        adds_equipment=["Great Weapon"],
    )
    assert warnings == []


def test_line_with_its_own_verb_ignores_the_header_verb() -> None:
    """A child that states its own action is parsed as written."""
    option, warnings = _option(
        "Replace Cavalry Spear with shortbows (+2 points per model)", OptionGroup(verb="take")
    )
    assert option.removes_equipment == ["Cavalry Spear"]
    assert option.adds_equipment == ["Shortbows"]
    assert warnings == []


def test_bare_line_without_a_header_verb_stays_verbatim() -> None:
    """Outside such a group there is no verb to supply: report, don't guess."""
    option, warnings = _option("Great Weapon (+1 point per model)")
    assert option.kind is OptionKind.OTHER
    assert any("kept verbatim" in w for w in warnings)


# --- printed cost forms -----------------------------------------------------


@pytest.mark.parametrize(
    ("cost", "points", "per_model"),
    [
        ("(+1 point per model)", 1, True),
        ("+1 point per model", 1, True),
        ("(+10 points per unit)", 10, False),
        ("+6 points per unit", 6, False),
        # No scope clause: the printed form omits it where only one model
        # can take the option, so the cost is paid once.
        ("(+10 points)", 10, False),
        ("+15 points", 15, False),
    ],
)
def test_cost_is_read_bracketed_or_bare_scoped_or_not(
    cost: str, points: int, per_model: bool
) -> None:
    """Every printed cost form maps onto the same two schema fields."""
    option, warnings = _option(f"Any unit may take Shields {cost}")
    assert (option.points, option.per_model) == (points, per_model)
    assert option.adds_equipment == ["Shields"]
    assert warnings == []


def test_cross_reference_is_not_part_of_the_name() -> None:
    """A "(see below)" pointer is page furniture, not the equipment's name."""
    option, warnings = _option("Any unit may take Drakeguns (see below) (+10 points per model)")
    assert option.name == "Drakeguns"
    assert option.adds_equipment == ["Drakeguns"]
    assert warnings == []


# --- options attached to one model ------------------------------------------


def test_line_attaches_the_option_to_the_model_it_names() -> None:
    """A line reading "An Ironbeard may take X" buys X for that model, not the unit."""
    option, warnings = _option(
        "An Ironbeard may take Cinderblast Bombs (see opposite) (+15 points)",
        printed={"Ironbreaker", "Ironbeard"},
    )
    assert option == UnitOption(
        name="Cinderblast Bombs",
        kind=OptionKind.EQUIPMENT,
        applies_to="Ironbeard",
        points=15,
        adds_equipment=["Cinderblast Bombs"],
    )
    assert warnings == []


def test_subject_is_only_a_model_when_the_unit_prints_its_profile() -> None:
    """A named subject with no profile row is not silently taken as a model."""
    option, warnings = _option(
        "An Ironbeard may take Cinderblast Bombs (+15 points)", printed={"Ironbreaker"}
    )
    assert option.applies_to is None
    assert option.kind is OptionKind.OTHER
    assert any("kept verbatim" in w for w in warnings)


def test_group_header_attaches_its_children_to_the_model() -> None:
    """A header naming a model scopes every option nested under it."""
    printed = {"Ironbreaker", "Ironbeard"}
    group, warnings = _group(
        "An Ironbeard may replace their Shield with one of the following:", printed
    )
    assert group == OptionGroup(applies_to="Ironbeard", verb="replace their Shield with")
    assert any("mutually exclusive" in w for w in warnings)

    option, _ = _option("Brace of Drakefire Pistols (+10 points)", group, printed)
    assert option == UnitOption(
        name="Brace of Drakefire Pistols",
        kind=OptionKind.EQUIPMENT,
        applies_to="Ironbeard",
        points=10,
        adds_equipment=["Brace of Drakefire Pistols"],
        removes_equipment=["Shield"],
    )


def test_line_states_its_own_availability_limit() -> None:
    """A restriction written into the line reads the same as in a header."""
    option, warnings = _option(
        "0-1 unit per 1,000 points may have the Drilled special rule +1 point per model"
    )
    assert option == UnitOption(
        name="Drilled",
        kind=OptionKind.SPECIAL_RULE,
        points=1,
        per_model=True,
        adds_rules=["Drilled"],
        limit="0-1 unit per 1000 points",
    )
    assert warnings == []


# --- option lines -----------------------------------------------------------


def test_champion_upgrade_line() -> None:
    """The champion shape: named role, flat per-unit cost."""
    option, warnings = _option("Upgrade one model to a Sentinel (champion) (+5 points per unit)")
    assert option == UnitOption(name="Sentinel", kind=OptionKind.CHAMPION, points=5)
    assert warnings == []


def test_command_upgrades_take_printed_names() -> None:
    """Lowercase source prose becomes the printed command names."""
    standard, _ = _option("Upgrade one model to a standard bearer (+5 points per unit)")
    assert standard.name == "Standard Bearer"
    assert standard.kind is OptionKind.STANDARD_BEARER
    musician, _ = _option("Upgrade one model to a musician (+5 points per unit)")
    assert musician.name == "Musician"
    assert musician.kind is OptionKind.MUSICIAN


def test_unknown_upgrade_role_degrades_to_other() -> None:
    """An upgrade target with no known role is kept, flagged for review."""
    option, warnings = _option("Upgrade one model to a war banner bearer (+10 points per unit)")
    assert option.kind is OptionKind.OTHER
    assert option.name == "War banner bearer"
    assert any("no known role" in w for w in warnings)


def test_rule_add_line() -> None:
    """A "have the X special rule" line adds the rule by its printed name."""
    option, warnings = _option(
        "The entire unit may have the Shieldwall special rule (+10 points per unit)"
    )
    assert option == UnitOption(
        name="Shieldwall", kind=OptionKind.SPECIAL_RULE, points=10, adds_rules=["Shieldwall"]
    )
    assert warnings == []


def test_rule_swap_line_charges_per_model() -> None:
    """A "replace the X special rule with Y" line swaps rules, priced per model."""
    option, warnings = _option(
        "Replace the Valour of Ages special rule with Veteran (+1 point per model)"
    )
    assert option == UnitOption(
        name="Veteran",
        kind=OptionKind.SPECIAL_RULE,
        points=1,
        per_model=True,
        adds_rules=["Veteran"],
        removes_rules=["Valour of Ages"],
    )
    assert warnings == []


def test_take_line_adds_equipment() -> None:
    """A "take X" line adds equipment under the linked name, as rendered."""
    option, warnings = _option("Any unit may take Shields (+1 point per model)")
    assert option == UnitOption(
        name="Shields",
        kind=OptionKind.EQUIPMENT,
        points=1,
        per_model=True,
        adds_equipment=["Shields"],
    )
    assert warnings == []


def test_equipment_swap_line() -> None:
    """A "replace X with Y" line swaps equipment, capitalising the prose side."""
    option, warnings = _option("Replace Cavalry Spear with shortbows (+2 points per model)")
    assert option == UnitOption(
        name="Shortbows",
        kind=OptionKind.EQUIPMENT,
        points=2,
        per_model=True,
        adds_equipment=["Shortbows"],
        removes_equipment=["Cavalry Spear"],
    )
    assert warnings == []


def test_magic_standard_line_is_a_budget() -> None:
    """The magic standard is a spend-up-to budget, not a flat cost."""
    option, warnings = _option("Purchase a magic standard worth up to 50 points")
    assert option == UnitOption(
        name="Magic standard", kind=OptionKind.MAGIC_STANDARD, points_budget=50
    )
    assert warnings == []


def test_magic_items_line_names_the_bearer() -> None:
    """A character's magic-item allowance keeps who it belongs to."""
    option, warnings = _option("A High Helm may purchase magic items up to a total of 25 points")
    assert option == UnitOption(
        name="High Helm magic items", kind=OptionKind.OTHER, points_budget=25
    )
    assert warnings == []


def test_group_limit_lands_on_the_option() -> None:
    """A limited group header's restriction reaches each child option."""
    option, _ = _option(
        "Purchase a magic standard worth up to 50 points",
        OptionGroup(limit="0-1 unit per 1000 points"),
    )
    assert option.limit == "0-1 unit per 1000 points"


def test_either_or_suffix_warns_about_lost_exclusivity() -> None:
    """The schema cannot express either/or yet; the choice is reported."""
    option, warnings = _option("Take Javelins (+1 point per model) Or:")
    assert option.adds_equipment == ["Javelins"]
    assert option.points == 1
    assert any("either/or" in w for w in warnings)


def test_unrecognised_line_is_kept_verbatim_as_other() -> None:
    """A line outside the grammar survives as kind: other, with a warning."""
    option, warnings = _option("March in perfect silence (+5 points per unit)")
    assert option == UnitOption(name="March in perfect silence", kind=OptionKind.OTHER, points=5)
    assert any("kept verbatim" in w for w in warnings)


def test_unrepresentable_line_is_dropped_loudly() -> None:
    """A costless unrecognised line fails the schema: dropped, but reported."""
    options: list[UnitOption] = []
    warnings: list[str] = []
    _append_option(
        options, "some-unit", _line("Fight with unusual valour"), OptionGroup(), set(), warnings
    )
    assert options == []
    assert any("DROPPED" in w for w in warnings)
