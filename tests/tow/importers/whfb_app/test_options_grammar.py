"""Option-line grammar tests on plain strings (no rich-text plumbing)."""

from avelorn.tow.importers.whfb_app.parse import _parse_group_limit, _parse_option_line
from avelorn.tow.importers.whfb_app.richtext import OptionLine
from avelorn.tow.schema.unit import OptionKind


def parse_line(text: str, limit: str | None = None) -> tuple:
    """Parse one option line.

    Returns:
        The parsed option and any warnings.
    """
    warnings: list[str] = []
    option = _parse_option_line("test", OptionLine(text=text, rules=[]), limit, warnings)
    return option, warnings


def test_champion_upgrade() -> None:
    """A "(champion)"-marked upgrade becomes a champion option."""
    option, warnings = parse_line(
        "Upgrade one model to a Sentinel (champion) (+5 points per unit)"
    )
    assert warnings == []
    assert option.kind is OptionKind.CHAMPION
    assert option.name == "Sentinel"
    assert option.points == 5
    assert option.per_model is False


def test_standard_bearer_and_musician_upgrades() -> None:
    """Command upgrades are recognised by role keyword."""
    bearer, _ = parse_line("Upgrade one model to a standard bearer (+5 points per unit)")
    assert bearer.kind is OptionKind.STANDARD_BEARER
    assert bearer.name == "Standard bearer"
    musician, _ = parse_line("Upgrade one model to a musician (+5 points per unit)")
    assert musician.kind is OptionKind.MUSICIAN
    assert musician.name == "Musician"


def test_unknown_upgrade_target_warns() -> None:
    """An upgrade to an unknown role degrades to kind=other."""
    option, warnings = parse_line("Upgrade one model to a Battle Goat (+5 points per unit)")
    assert option.kind is OptionKind.OTHER
    assert warnings


def test_special_rule_purchase() -> None:
    """Buying a special rule records it in adds_rules."""
    option, warnings = parse_line(
        "Any unit of Elven Spearmen may have the Shieldwall special rule (+10 points per unit)"
    )
    assert warnings == []
    assert option.kind is OptionKind.SPECIAL_RULE
    assert option.name == "Shieldwall"
    assert option.adds_rules == ["Shieldwall"]
    assert option.points == 10


def test_special_rule_swap() -> None:
    """Replacing a rule records both sides and the group limit."""
    option, _ = parse_line(
        "Replace the Valour of Ages special rule with Veteran (+1 point per model)",
        limit="0-1 unit per 1000 points",
    )
    assert option.kind is OptionKind.SPECIAL_RULE
    assert option.name == "Veteran"
    assert option.adds_rules == ["Veteran"]
    assert option.removes_rules == ["Valour of Ages"]
    assert option.per_model is True
    assert option.limit == "0-1 unit per 1000 points"


def test_equipment_take() -> None:
    """Taking equipment records it in adds_equipment."""
    option, warnings = parse_line(
        "Any unit of Elven Archers may take Light Armour (+1 point per model)"
    )
    assert warnings == []
    assert option.kind is OptionKind.EQUIPMENT
    assert option.name == "Light Armour"


def test_magic_standard() -> None:
    """A magic standard becomes a points budget, not a flat cost."""
    option, warnings = parse_line("Purchase a magic standard worth up to 50 points")
    assert warnings == []
    assert option.kind is OptionKind.MAGIC_STANDARD
    assert option.points_budget == 50
    assert option.points is None


def test_unknown_line_kept_verbatim_with_warning() -> None:
    """An unmatched line is kept verbatim with a warning."""
    option, warnings = parse_line("May ride a war hippogriff (+200 points per unit)")
    assert option.kind is OptionKind.OTHER
    assert option.name == "May ride a war hippogriff"
    assert option.points == 200
    assert warnings


def test_group_limits() -> None:
    """Group headers map to limits; unknown headers are kept verbatim."""
    warnings: list[str] = []
    assert _parse_group_limit("test", "Any unit may:", warnings) is None
    assert _parse_group_limit("test", "The entire unit may:", warnings) is None
    assert (
        _parse_group_limit("test", "0-1 unit of Elven Spearmen per 1,000 points may:", warnings)
        == "0-1 unit per 1000 points"
    )
    assert warnings == []
    kept = _parse_group_limit("test", "Units in a Sea Guard detachment may:", warnings)
    assert kept == "Units in a Sea Guard detachment may:"
    assert warnings
