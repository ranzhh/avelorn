"""The CLI's commands: what each one reads out of the real corpus under data/."""

import shutil
from pathlib import Path

import pytest
import yaml

from avelorn.cli import commands
from avelorn.tow.data import DATA_DIR, TOWRepository

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
    assert "White Lion           5  5   4   4  3  1  5  1  8" in printed
    assert "Guardian (champion)  5  5   4   4  3  1  5  2  8" in printed


def test_show_prints_what_the_datasheet_offers() -> None:
    """Equipment, rules, and the options with the cost shape each carries."""
    printed = "\n".join(commands.show_unit(REPO, "white-lions-of-chrace"))
    assert "Chracian Great Blade" in printed
    assert "Lion Cloak" in printed
    assert "Veteran (1 point/model)" in printed
    assert "Magic standard (up to 50 points of magic items)" in printed


def test_show_marks_the_rules_the_engine_does_not_apply() -> None:
    """A printed rule with no effects is starred, and the star is explained once."""
    printed = "\n".join(commands.show_unit(REPO, "dwarf-warriors"))
    assert "Close Order *" in printed
    assert "Shieldwall\n" in printed
    assert printed.count("* no entry or no effects") == 1


def test_show_refuses_an_unknown_slug_and_says_where_to_look() -> None:
    """A missed slug is the user's question, answered with how to ask it properly."""
    with pytest.raises(LookupError, match="no unit 'wood-elves'"):
        commands.show_unit(REPO, "wood-elves")


def test_rules_list_says_which_entries_reach_the_maths() -> None:
    """The listing's point is the FACTORS column: text held is not text applied."""
    lines = commands.list_rules(REPO)
    assert len(lines) == len(REPO.rules) + 1
    stubborn = next(line for line in lines if line.startswith("stubborn"))
    assert stubborn.split()[-2:] == ["yes", "5"]
    assert any(line.split()[-2] == "no" for line in lines[1:])


def test_coverage_leads_with_what_the_ledger_does_not_match(tmp_path: Path) -> None:
    """A gap the ledger misses and an entry nothing needs are the first lines printed."""
    data = tmp_path / "data"
    shutil.copytree(DATA_DIR, data)
    ledger = data / "tow/unmodelled.yaml"
    entries = yaml.safe_load(ledger.read_text())
    dropped = entries[0]
    entries[0] = {**dropped, "subject": "No Such Rule"}
    ledger.write_text(yaml.safe_dump(entries))

    printed = commands.show_coverage(TOWRepository(data_dir=data))
    assert printed[0] == "!! 1 UNACKNOWLEDGED -- add each to data/tow/unmodelled.yaml:"
    assert printed[1].startswith(f"!!   {dropped['kind']}: {dropped['subject']}  (")
    assert printed[3:5] == [
        "!! 1 STALE -- delete from data/tow/unmodelled.yaml:",
        f"!!   {dropped['kind']}: No Such Rule",
    ]


def test_rules_show_prints_the_text_the_effects_and_what_is_left_out() -> None:
    """One rule read whole: prose, the authored YAML, and its notes."""
    printed = "\n".join(commands.show_rule(REPO, "stubborn"))
    assert "Stubborn  (stubborn)" in printed
    assert "Special Rules, page 178" in printed
    assert "- fall-back-in-good-order" in printed
    assert "Not covered:" in printed


def test_rules_show_names_a_granted_rule_as_it_prints() -> None:
    """Arrows of Isha grants Armour Bane (1), not the reference it is authored as."""
    printed = "\n".join(commands.show_rule(REPO, "arrows-of-isha"))
    assert "grants: Armour Bane (1)" in printed


def test_rules_show_points_a_miss_at_the_rule_listing() -> None:
    """A slug with no entry cannot be shown, so the miss says where the slugs are listed."""
    with pytest.raises(LookupError, match="avelorn rules list"):
        commands.show_rule(REPO, "unprinted-rule")
