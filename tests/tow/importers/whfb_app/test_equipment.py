"""Weapons of War parser tests against captured whfb.app payloads.

Fixtures are real `/_next/data/.../weapons-of-war/<slug>.json` entries
with Contentful boilerplate pruned to the fields the parser reads.
Recapture by re-running the pruning snippet in the PR that added them, or
inspect live pages with:

    uv run python scripts/import_whfb_app.py weapon <slug> --dry-run
"""

import json
from pathlib import Path

import pytest
import yaml

from avelorn.tow.importers.whfb_app.equipment import parse_armour, parse_weapon
from avelorn.tow.importers.whfb_app.parse import WhfbParseError
from avelorn.tow.importers.whfb_app.yamlout import armour_to_yaml, weapon_to_yaml
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.weapon import Weapon

FIXTURES = Path(__file__).parent / "fixtures" / "weapons-of-war"

WEAPON_SLUGS = [
    "longbow",
    "warbow",
    "hand-weapon",
    "thrusting-spear",
    "lance",
    "brace-of-pistols",
]
ARMOUR_SLUGS = ["light-armour", "shield"]


def load_fixture(slug: str) -> dict:
    """Load a captured weapons-of-war entry.

    Returns:
        The entry as a dict.
    """
    return json.loads((FIXTURES / f"{slug}.json").read_text())


def test_fixture_lists_cover_the_directory() -> None:
    """Every captured payload is claimed by exactly one parser's list."""
    assert sorted(WEAPON_SLUGS + ARMOUR_SLUGS) == sorted(p.stem for p in FIXTURES.glob("*.json"))


@pytest.mark.parametrize("slug", WEAPON_SLUGS)
def test_weapon_fixtures_parse(slug: str) -> None:
    """Every captured weapon payload maps onto a valid Weapon."""
    result = parse_weapon(load_fixture(slug))
    assert result.weapon.id == slug


@pytest.mark.parametrize("slug", ARMOUR_SLUGS)
def test_armour_fixtures_parse(slug: str) -> None:
    """Every captured armour payload maps onto a valid Armour."""
    result = parse_armour(load_fixture(slug))
    assert result.armour.id == slug


def test_longbow_profile() -> None:
    """A plain missile weapon: absolute Strength, printed rules kept whole."""
    result = parse_weapon(load_fixture("longbow"))
    assert result.warnings == []
    (profile,) = result.weapon.profiles
    assert profile.name is None  # "Longbow (Profile)" adds nothing
    assert profile.range == 30
    assert profile.strength.base == 3
    assert profile.armour_piercing == 0
    assert profile.special_rules == ["Armour Bane (1)", "Volley Fire"]


def test_warbow_strength_is_wielder_relative() -> None:
    """Printed "S" parses to a relative Strength."""
    (profile,) = parse_weapon(load_fixture("warbow")).weapon.profiles
    assert profile.strength.is_relative
    assert profile.strength.resolve(3) == 3


def test_lance_keeps_printed_notes() -> None:
    """Usage restrictions survive as verbatim notes text."""
    weapon = parse_weapon(load_fixture("lance")).weapon
    assert weapon.notes is not None
    assert weapon.notes.startswith("Models whose troop type is cavalry or monster only.")
    (profile,) = weapon.profiles
    assert profile.strength.modifier == 2
    assert profile.armour_piercing == -2


def test_brace_of_pistols_has_named_profiles() -> None:
    """A two-row weapon keeps both rows, named as printed."""
    result = parse_weapon(load_fixture("brace-of-pistols"))
    names = [p.name for p in result.weapon.profiles]
    assert names == ["Ranged", "Combat"]
    # The page's "Ranged:"/"Combat:" heading paragraphs are surfaced, not dropped.
    assert any("Ranged:" in w for w in result.warnings)


def test_light_armour_value() -> None:
    """A suit parses to its printed armour value."""
    result = parse_armour(load_fixture("light-armour"))
    assert result.armour.armour_value == 6
    assert result.armour.armour_value_improvement is None


def test_shield_improvement_and_notes() -> None:
    """An addition parses to an improvement; rule prose lands in notes."""
    result = parse_armour(load_fixture("shield"))
    assert result.armour.armour_value_improvement == 1
    assert result.armour.notes is not None
    assert "Requires Two Hands" in result.armour.notes
    # Flavour prose is surfaced for the reviewing human, not dropped.
    assert any("not captured" in w for w in result.warnings)


def test_parsers_reject_the_other_kind() -> None:
    """A weapon page is not armour and vice versa."""
    with pytest.raises(WhfbParseError, match="weapon profile"):
        parse_armour(load_fixture("longbow"))
    with pytest.raises(WhfbParseError, match="no weapon profile"):
        parse_weapon(load_fixture("shield"))


@pytest.mark.parametrize("slug", WEAPON_SLUGS)
def test_weapon_yaml_round_trips(slug: str) -> None:
    """Generated weapon YAML reloads into an equal Weapon."""
    weapon = parse_weapon(load_fixture(slug)).weapon
    assert Weapon.model_validate(yaml.safe_load(weapon_to_yaml(weapon))) == weapon


@pytest.mark.parametrize("slug", ARMOUR_SLUGS)
def test_armour_yaml_round_trips(slug: str) -> None:
    """Generated armour YAML reloads into an equal Armour."""
    armour = parse_armour(load_fixture(slug)).armour
    assert Armour.model_validate(yaml.safe_load(armour_to_yaml(armour))) == armour


def test_weapon_yaml_matches_hand_authored_style() -> None:
    """Profiles are flow mappings under a source-comment header."""
    weapon = parse_weapon(load_fixture("longbow")).weapon
    text = weapon_to_yaml(weapon, source_url="https://tow.whfb.app/weapons-of-war/longbow")
    lines = text.splitlines()
    assert lines[0] == "# Source: https://tow.whfb.app/weapons-of-war/longbow"
    assert "  - { R: 30, S: 3, AP: '-', special_rules: [Armour Bane (1), Volley Fire] }" in lines
