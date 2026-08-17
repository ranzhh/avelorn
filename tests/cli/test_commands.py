"""The CLI's commands: what each one reads out of the real corpus under data/."""

import pytest

from avelorn.cli import commands
from avelorn.tow.data import TOWRepository

REPO = TOWRepository()


def test_units_lists_every_datasheet() -> None:
    """The listing covers the corpus, one line per unit plus the header."""
    lines = commands.list_units(REPO)
    assert len(lines) == len(REPO.units) + 1
    assert all(slug in "\n".join(lines) for slug in REPO.units)


def test_show_prints_every_profile_row() -> None:
    """A datasheet with a champion row prints both rows, under the characteristics."""
    printed = "\n".join(commands.show_unit(REPO, "white-lions-of-chrace"))
    assert "M  WS  BS  S  T  W  I  A  Ld" in printed
    assert "White Lion  5  5   4   4  3  1  5  1  8" in printed
    assert "Guardian    5  5   4   4  3  1  5  2  8" in printed


def test_show_prints_what_the_datasheet_offers() -> None:
    """Equipment, rules, and the options with the cost shape each carries."""
    printed = "\n".join(commands.show_unit(REPO, "white-lions-of-chrace"))
    assert "Chracian Great Blade" in printed
    assert "Lion Cloak" in printed
    assert "Veteran (1 point/model)" in printed
    assert "Magic standard (up to 50 points of magic items)" in printed


def test_show_refuses_an_unknown_slug_and_says_where_to_look() -> None:
    """A missed slug is the user's question, answered with how to ask it properly."""
    with pytest.raises(LookupError, match="no unit 'wood-elves'"):
        commands.show_unit(REPO, "wood-elves")


def test_rules_list_says_which_entries_reach_the_maths() -> None:
    """The listing's point is the FACTORS column: text held is not text applied."""
    lines = commands.list_rules(REPO)
    assert len(lines) == len(REPO.rules) + 1
    stubborn = next(line for line in lines if line.startswith("stubborn"))
    assert stubborn.split()[-2:] == ["yes", "3"]  # effects, and three units print it
    # Every entry folds, because one that did not would not be filed at all.
    assert all(line.split()[-2] == "yes" for line in lines[1:])


def test_unmodelled_reports_a_name_with_no_entry_and_who_prints_it() -> None:
    """A rule the corpus prints without an entry is invisible in the registry."""
    printed = "\n".join(commands.list_unmodelled(REPO))
    assert "\nClose Order\n" in printed
    assert "elven-spearmen" in printed


def test_unmodelled_resolves_a_printed_parameter_before_judging_it() -> None:
    """Armour Bane (1) is modelled by the entry filed under (X), so it is not reported.

    Three weapons print the parameterised name and no file carries it, so a
    plain lookup would report it missing. Fielding resolves it; so does this.
    """
    printed_by = {
        name
        for weapon in REPO.weapons.values()
        for p in weapon.profiles
        for name in p.special_rules
    }
    assert "Armour Bane (1)" in printed_by
    assert "Armour Bane" not in "\n".join(commands.list_unmodelled(REPO))


def test_rules_show_prints_the_text_the_effects_and_what_is_left_out() -> None:
    """One rule read whole: prose, the authored YAML, and its notes."""
    printed = "\n".join(commands.show_rule(REPO, "stubborn"))
    assert "Stubborn  (stubborn)" in printed
    assert "Special Rules, page 178" in printed
    assert "break: fall-back-in-good-order" in printed
    assert "Not covered:" in printed


def test_rules_show_points_a_miss_at_the_unmodelled_report() -> None:
    """A printed rule with no entry cannot be shown, so the miss says where it is named."""
    with pytest.raises(LookupError, match="--unmodelled"):
        commands.show_rule(REPO, "close-order")
