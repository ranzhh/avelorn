"""The army-list layer: Complement, a unit as mustered into a list."""

import pytest
from pydantic import ValidationError

from avelorn.tow.data import TOWRepository
from avelorn.tow.muster import Complement
from avelorn.tow.schema.unit import OptionKind, Unit, UnitOption

REPO = TOWRepository()


@pytest.fixture
def spearmen_unit() -> Unit:
    """The Elven Spearmen datasheet, whose options a Complement is built from.

    Returns:
        The validated unit model.
    """
    return REPO.units["elven-spearmen"]


def test_complement_points_sum_models_and_flat_options(spearmen_unit: Unit) -> None:
    """A complement's points are per-model cost plus flat per-unit options."""
    # 10 Spearmen, plus a Standard Bearer (5) and Musician (5). The per-model
    # cost is read from the datasheet: what is under test is the arithmetic,
    # not what the army list charges this week.
    mustered = Complement(unit=spearmen_unit, size=10, options=["Standard Bearer", "Musician"])
    assert mustered.points == 10 * spearmen_unit.points + 5 + 5


def test_complement_per_model_option_costs_once_per_model(spearmen_unit: Unit) -> None:
    """A per-model option is charged for every model, and folds its rules."""
    # Veteran: +1 pt/model, adds "Veteran", removes "Valour of Ages".
    mustered = Complement(unit=spearmen_unit, size=10, options=["Veteran"])
    assert mustered.points == 10 * spearmen_unit.points + 10 * 1
    assert "Veteran" in mustered.special_rules
    assert "Valour of Ages" not in mustered.special_rules


def test_complement_option_adds_rule(spearmen_unit: Unit) -> None:
    """An option's adds_rules appears in the effective special rules."""
    mustered = Complement(unit=spearmen_unit, size=10, options=["Shieldwall"])
    assert "Shieldwall" in mustered.special_rules
    # Untaken options leave the datasheet loadout untouched.
    assert Complement(unit=spearmen_unit, size=10).special_rules == spearmen_unit.special_rules


def test_complement_size_below_minimum_rejected(spearmen_unit: Unit) -> None:
    """A size under the datasheet's minimum fails validation."""
    with pytest.raises(ValidationError, match="below the unit's minimum"):
        Complement(unit=spearmen_unit, size=4)


def test_complement_unknown_option_rejected(spearmen_unit: Unit) -> None:
    """An option the datasheet does not offer fails validation."""
    with pytest.raises(ValidationError, match="not offered"):
        Complement(unit=spearmen_unit, size=10, options=["Warpstone Amulet"])


def test_complement_duplicate_option_rejected(spearmen_unit: Unit) -> None:
    """The same option chosen twice fails validation."""
    with pytest.raises(ValidationError, match="duplicates"):
        Complement(unit=spearmen_unit, size=10, options=["Musician", "Musician"])


@pytest.fixture
def spearmen_with_a_sentinel_option(spearmen_unit: Unit) -> Unit:
    """Elven Spearmen with a blade bought for the Sentinel alone.

    The shape Ironbreakers prints for the Ironbeard's wargear, on a
    datasheet the rest of these tests already use.

    Returns:
        The datasheet with one model-scoped option added.
    """
    scoped = UnitOption(
        name="Ithilmar Blade",
        kind=OptionKind.EQUIPMENT,
        applies_to="Sentinel",
        points=5,
        adds_equipment=["Ithilmar Blade"],
    )
    return spearmen_unit.model_copy(update={"options": [*spearmen_unit.options, scoped]})


def test_complement_model_scoped_option_rejected(spearmen_with_a_sentinel_option: Unit) -> None:
    """An option bought for one model has no part to fold into: refuse it."""
    with pytest.raises(ValidationError, match="attach to a single model"):
        Complement(unit=spearmen_with_a_sentinel_option, size=10, options=["Ithilmar Blade"])


def test_complement_unit_wide_options_unaffected(spearmen_with_a_sentinel_option: Unit) -> None:
    """The refusal is about the one option, not the datasheet that offers it."""
    mustered = Complement(unit=spearmen_with_a_sentinel_option, size=10, options=["Shieldwall"])
    assert "Shieldwall" in mustered.special_rules
    assert "Ithilmar Blade" not in mustered.equipment


def test_the_reavers_replace_option_swaps_the_spear_for_the_shortbow() -> None:
    """The canonicalised Shortbows option arms the Shortbow and drops the spear.

    The option is printed "Replace cavalry spears with shortbows"; the
    importer canonicalises its prose plural against the corpus, so the
    mustered loadout carries the real entry — the regression that needed a
    hand-edit before the importer learned to spell references as filed.
    """
    from avelorn.tow.contingent import Contingent

    reavers = Contingent.deploy("ellyrian-reavers", 5, ["Shortbows"], data=REPO)
    carried = [weapon.name for weapon in reavers.loadout.weapons]
    assert "Shortbow" in carried
    assert "Cavalry Spear" not in carried
