"""avelorn.tow.data: the TOWRepository registries and their two keys."""

import shutil
from pathlib import Path

import pytest

from avelorn.core.registry import UnknownNameError
from avelorn.tow.data import DATA_DIR, TOWRepository

REPO = TOWRepository()


def _corpus_filing(tmp_path: Path, slug: str, under: str) -> Path:
    """Copy the committed data tree, filing ``slug`` under a second army too.

    The shape a shared datasheet takes on disk: nine of them are fielded by
    more than one army, so the same file sits in each army's directory.

    Returns:
        The second copy's path.
    """
    data = tmp_path / "data"
    shutil.copytree(DATA_DIR, data)
    original = next(data.glob(f"tow/armies/*/units/{slug}.yaml"))
    second = data / "tow/armies" / under / "units" / f"{slug}.yaml"
    second.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(original, second)
    return second


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


def test_a_datasheet_filed_under_two_armies_loads_once(tmp_path: Path) -> None:
    """Copies that agree are the one datasheet they are, not a duplicate-slug error."""
    _corpus_filing(tmp_path, "elven-archers", under="wood-elf-realms")
    units = TOWRepository(data_dir=tmp_path / "data").units
    assert len(units) == len(REPO.units)
    assert units["elven-archers"] == REPO.units["elven-archers"]


def test_copies_may_differ_in_comments(tmp_path: Path) -> None:
    """Agreement is on the parsed datasheet: a file's comments are not game data."""
    second = _corpus_filing(tmp_path, "elven-archers", under="wood-elf-realms")
    second.write_text("# a hand-authored note the other copy has not got\n" + second.read_text())
    assert "elven-archers" in TOWRepository(data_dir=tmp_path / "data").units


def test_copies_that_disagree_fail_the_load_naming_both(tmp_path: Path) -> None:
    """A stale copy is not a variant: the game prints one datasheet per slug."""
    second = _corpus_filing(tmp_path, "elven-archers", under="wood-elf-realms")
    second.write_text(second.read_text().replace("points: 9", "points: 11"))
    stale = TOWRepository(data_dir=tmp_path / "data")
    with pytest.raises(ValueError, match=r"unit 'elven-archers' differs between .*\(on: points\)"):
        _ = stale.units


def test_a_datasheet_names_the_army_filing_it() -> None:
    """The army is the directory, which the repository reads off the path."""
    assert REPO.fielded_by["elven-archers"] == ("high-elf-realms",)
    assert REPO.fielded_by["dwarf-warriors"] == ("dwarfen-mountain-holds",)


def test_every_datasheet_is_fielded_by_someone() -> None:
    """A unit reaches the registry by being filed under an army, so none is orphaned."""
    assert set(REPO.fielded_by) == set(REPO.units)


def test_a_datasheet_filed_under_two_armies_names_both(tmp_path: Path) -> None:
    """A mount several armies take belongs to every branch of a browser that fields it."""
    _corpus_filing(tmp_path, "elven-archers", under="wood-elf-realms")
    shared = TOWRepository(data_dir=tmp_path / "data")
    assert shared.fielded_by["elven-archers"] == ("high-elf-realms", "wood-elf-realms")


def test_printed_references_are_spelled_as_their_entries() -> None:
    """A reference that is a loose variant of an existing entry is a data error.

    The engine resolves printed names exactly, on purpose; the importer
    canonicalises what it writes against the corpus as it stands. What
    neither can catch is time: an entry imported *after* the files that
    reference it leaves those files spelling it as the site did. This is
    where that fails loudly — a reference matching an entry up to case or a
    trailing plural "s" without matching it exactly names the file to
    re-import. A reference matching nothing is not an offence: its entry may
    simply not exist yet, which the coverage and unfactored reports own.
    """
    from avelorn.tow.importers.whfb_app.canon import canonical
    from avelorn.tow.schema.rule import GrantEffect

    equipment = {item.name for item in (*REPO.weapons.values(), *REPO.armoury.values())}
    rules = {rule.name for rule in REPO.rules.values()}

    references: list[tuple[str, str, set[str]]] = []
    for unit in REPO.units.values():
        for name in unit.equipment:
            references.append((unit.id, name, equipment))
        for name in unit.special_rules:
            references.append((unit.id, name, rules))
        for option in unit.options:
            for name in (*option.adds_equipment, *option.removes_equipment):
                references.append((unit.id, name, equipment))
            for name in (*option.adds_rules, *option.removes_rules):
                references.append((unit.id, name, rules))
    for weapon in REPO.weapons.values():
        for profile in weapon.profiles:
            for name in profile.special_rules:
                references.append((weapon.id, name, rules))
    for troop_type in REPO.troop_types.values():
        for name in troop_type.special_rules:
            references.append((troop_type.id, name, rules))
    for rule in REPO.rules.values():
        for effect in rule.effects:
            if isinstance(effect, GrantEffect):
                references.append((rule.id, effect.grants, rules))

    offences = [
        f"{owner}: {name!r} should be spelled {found!r}"
        for owner, name, names in references
        if name not in names and (found := canonical(name, names)) is not None
    ]
    assert offences == []
