"""Weapon and armour schema tests: printed-convention parsing."""

import pytest
from pydantic import ValidationError

from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.weapon import Weapon, WeaponProfile, WeaponStrength


@pytest.mark.parametrize(
    ("printed", "base", "modifier"),
    [
        (4, 4, 0),
        ("4", 4, 0),
        ("S", None, 0),
        ("S+2", None, 2),
        ("S-1", None, -1),
    ],
)
def test_strength_parses_printed_forms(
    printed: int | str, base: int | None, modifier: int
) -> None:
    """Strength accepts absolute values and wielder-relative "S±N" forms."""
    strength = WeaponStrength.model_validate(printed)
    assert strength.base == base
    assert strength.modifier == modifier


@pytest.mark.parametrize("printed", ["T", "S+", "2+2", ""])
def test_strength_rejects_unknown_forms(printed: str) -> None:
    """Anything outside the printed grammar is an error, not a guess."""
    with pytest.raises(ValidationError):
        WeaponStrength.model_validate(printed)


def test_strength_rejects_absolute_with_modifier() -> None:
    """A modifier only makes sense relative to the wielder."""
    with pytest.raises(ValidationError, match="modifier"):
        WeaponStrength(base=4, modifier=2)


@pytest.mark.parametrize(
    ("printed", "wielder", "effective"),
    [("S", 3, 3), ("S+2", 3, 5), ("S-1", 4, 3), (4, 3, 4)],
)
def test_strength_resolve(printed: int | str, wielder: int, effective: int) -> None:
    """Relative Strength tracks the wielder; absolute ignores it."""
    assert WeaponStrength.model_validate(printed).resolve(wielder) == effective


@pytest.mark.parametrize(("printed", "spelled"), [(4, "4"), ("S", "S"), ("S+2", "S+2")])
def test_strength_printed_round_trips(printed: int | str, spelled: str) -> None:
    """`printed` re-emits the rulebook spelling."""
    assert WeaponStrength.model_validate(printed).printed == spelled


def test_profile_parses_printed_row() -> None:
    """A profile row reads like the rulebook chart, dashes included."""
    profile = WeaponProfile.model_validate(
        {"R": "Combat", "S": "S+2", "AP": "-", "special_rules": ["Armour Bane (1)"]}
    )
    assert profile.range == "Combat"
    assert profile.armour_piercing == 0
    assert not profile.is_missile


def test_profile_rejects_positive_armour_piercing() -> None:
    """AP is always a penalty to the save roll."""
    with pytest.raises(ValidationError):
        WeaponProfile.model_validate({"R": 24, "S": 3, "AP": 1})


def test_missile_profile_picks_the_ranged_row() -> None:
    """A mixed weapon exposes its ranged row; pure melee exposes none."""
    brace = Weapon(
        id="brace-of-pistols",
        name="Brace of Pistols",
        profiles=[
            WeaponProfile.model_validate({"name": "Combat", "R": "Combat", "S": "S"}),
            WeaponProfile.model_validate({"name": "Ranged", "R": 12, "S": 4, "AP": -1}),
        ],
    )
    assert brace.missile_profile is not None
    assert brace.missile_profile.range == 12

    melee = Weapon(
        id="hand-weapon",
        name="Hand Weapon",
        profiles=[WeaponProfile.model_validate({"R": "Combat", "S": "S"})],
    )
    assert melee.missile_profile is None


def test_armour_requires_exactly_one_shape() -> None:
    """A suit has a value, an addition has an improvement — never both."""
    Armour(id="light-armour", name="Light Armour", armour_value=6)
    Armour(id="shield", name="Shield", armour_value_improvement=1)
    with pytest.raises(ValidationError, match="exactly one"):
        Armour(id="x", name="X", armour_value=6, armour_value_improvement=1)
    with pytest.raises(ValidationError, match="exactly one"):
        Armour(id="x", name="X")
