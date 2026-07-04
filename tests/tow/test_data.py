"""avelorn.tow.data: the TOWRepository registries and their keys."""

from avelorn.tow.data import TOWRepository

REPO = TOWRepository()


def test_units_and_weapons_are_keyed_by_slug() -> None:
    """Units and weapons are addressed by slug (the filename)."""
    assert REPO.units["elven-spearmen"].id == "elven-spearmen"
    assert REPO.weapons["longbow"].name == "Longbow"


def test_units_span_every_army() -> None:
    """The unit registry is not scoped to one army."""
    assert "elven-spearmen" in REPO.units  # high-elf-realms


def test_armoury_and_rules_are_keyed_by_display_name() -> None:
    """Armour and rules key on display name — the form the engine resolves."""
    assert REPO.armoury["Shield"].name == "Shield"
    assert REPO.rules["Valour of Ages"].id == "valour-of-ages"


def test_registries_load_once_per_instance() -> None:
    """A cached_property hands back the same dict on repeated access."""
    assert REPO.rules is REPO.rules
