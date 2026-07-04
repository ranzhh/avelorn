"""The double-keyed Registry: slug addressing, name resolution, strictness."""

from dataclasses import dataclass

import pytest

from avelorn.core.registry import Registry, UnknownNameError


@dataclass(frozen=True)
class _Entry:
    id: str
    name: str


SHIELD = _Entry(id="shield", name="Shield")
LIGHT = _Entry(id="light-armour", name="Light Armour")


def test_addresses_by_slug() -> None:
    """The mapping interface speaks slugs: getitem, contains, iteration."""
    registry = Registry([SHIELD, LIGHT], kind="armour")
    assert registry["shield"] is SHIELD
    assert "light-armour" in registry
    assert list(registry) == ["shield", "light-armour"]
    assert len(registry) == 2


def test_unknown_slug_raises_key_error() -> None:
    """Slug addressing keeps plain mapping semantics on a miss."""
    registry = Registry([SHIELD], kind="armour")
    with pytest.raises(KeyError):
        registry["helmet"]


def test_resolves_display_names() -> None:
    """by_name turns a printed name into the same registered entry."""
    registry = Registry([SHIELD, LIGHT], kind="armour")
    assert registry.by_name("Shield") is SHIELD
    assert registry.by_name("Light Armour") is LIGHT


def test_unknown_name_raises_with_kind_and_name() -> None:
    """A name miss is loud and carries what missed, for the catch site."""
    registry = Registry([SHIELD], kind="armour")
    with pytest.raises(UnknownNameError, match="no armour named 'Helmet'") as excinfo:
        registry.by_name("Helmet")
    assert excinfo.value.kind == "armour"
    assert excinfo.value.name == "Helmet"
    assert isinstance(excinfo.value, LookupError)


def test_duplicate_slug_rejected_at_construction() -> None:
    """Two entries sharing a slug fail the load, not a later lookup."""
    with pytest.raises(ValueError, match="duplicate armour slug 'shield'"):
        Registry([SHIELD, _Entry(id="shield", name="Tower Shield")], kind="armour")


def test_duplicate_name_rejected_at_construction() -> None:
    """Two entries sharing a printed name would make resolution ambiguous."""
    with pytest.raises(ValueError, match="duplicate armour name 'Shield'"):
        Registry([SHIELD, _Entry(id="tower-shield", name="Shield")], kind="armour")


def test_empty_registry() -> None:
    """An empty registry addresses nothing and resolves nothing."""
    registry: Registry[_Entry] = Registry()
    assert len(registry) == 0
    with pytest.raises(UnknownNameError, match="no entry named"):
        registry.by_name("Shield")


def test_resolve_partitions_found_and_missing_in_order() -> None:
    """Bulk resolution tolerates misses: entries and unknowns, input order."""
    registry = Registry([SHIELD, LIGHT], kind="armour")
    found, missing = registry.resolve(["Light Armour", "Helmet", "Shield", "Barding"])
    assert found == [LIGHT, SHIELD]
    assert missing == ["Helmet", "Barding"]
