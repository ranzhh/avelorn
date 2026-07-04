"""avelorn.tow.data: the TOWRepository registries and their two keys."""

import pytest

from avelorn.core.registry import UnknownNameError
from avelorn.tow.data import TOWRepository

REPO = TOWRepository()


def test_registries_are_addressed_by_slug() -> None:
    """Every registry addresses its entries by slug."""
    assert REPO.units["elven-spearmen"].name == "Elven Spearmen"
    assert REPO.weapons["longbow"].name == "Longbow"
    assert REPO.armoury["shield"].name == "Shield"
    assert REPO.rules["armour-bane"].name == "Armour Bane (X)"


def test_units_span_every_army() -> None:
    """The unit registry is not scoped to one army."""
    assert "elven-spearmen" in REPO.units  # high-elf-realms


def test_display_names_resolve_via_by_name() -> None:
    """Printed names — the form cross-references take — resolve explicitly."""
    assert REPO.armoury.by_name("Shield").id == "shield"
    assert REPO.rules.by_name("Valour of Ages").id == "valour-of-ages"


def test_unknown_display_name_is_loud() -> None:
    """A name miss raises; callers choose to catch and degrade visibly."""
    with pytest.raises(UnknownNameError, match="no rule named"):
        REPO.rules.by_name("Sureshot")


def test_registries_load_once_per_instance() -> None:
    """A cached_property hands back the same registry on repeated access."""
    assert REPO.rules is REPO.rules
