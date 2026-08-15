"""The CLI's commands: what each one reads out of the real corpus under data/."""

import pytest

from avelorn.cli import commands
from avelorn.tow.data import TOWRepository

REPO = TOWRepository()


def test_units_lists_every_datasheet() -> None:
    """The listing covers the corpus, one line per unit plus the header."""
    lines = commands.units(REPO)
    assert len(lines) == len(REPO.units) + 1
    assert all(slug in "\n".join(lines) for slug in REPO.units)


def test_show_prints_every_profile_row() -> None:
    """A datasheet with a champion row prints both rows, under the characteristics."""
    printed = "\n".join(commands.show(REPO, "white-lions-of-chrace"))
    assert "M  WS  BS  S  T  W  I  A  Ld" in printed
    assert "White Lion  5  5   4   4  3  1  5  1  8" in printed
    assert "Guardian    5  5   4   4  3  1  5  2  8" in printed


def test_show_prints_what_the_datasheet_offers() -> None:
    """Equipment, rules, and the options with the cost shape each carries."""
    printed = "\n".join(commands.show(REPO, "white-lions-of-chrace"))
    assert "Chracian Great Blade" in printed
    assert "Lion Cloak" in printed
    assert "Veteran (1 point/model)" in printed
    assert "Magic standard (up to 50 points of magic items)" in printed


def test_show_refuses_an_unknown_slug_and_says_where_to_look() -> None:
    """A missed slug is the user's question, answered with how to ask it properly."""
    with pytest.raises(LookupError, match="no unit 'wood-elves'"):
        commands.show(REPO, "wood-elves")
