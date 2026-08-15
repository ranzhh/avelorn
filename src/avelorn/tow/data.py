"""Locating and loading the hand-authored game data under ``data/``.

``data/`` is the single source of truth — armies (and their units),
weapons, armour, and rules. :class:`TOWRepository` is the one place that
knows the tree's layout, so tests, demos, and the app read through it.
"""

from collections.abc import Sequence
from functools import cached_property
from pathlib import Path

from avelorn.core.loading import load_yaml, load_yaml_dir
from avelorn.core.registry import Registry
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.troop_type import TroopTypeProfile
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon

# data/ sits at the repository root, beside src/. Located from this file so the
# path holds regardless of the caller's working directory.
DATA_DIR = Path(__file__).parents[3] / "data"


def rule_paths(data_dir: Path = DATA_DIR) -> list[Path]:
    """Every rule-entry file: the shared rules, plus each army's magic items.

    The one statement of where rule entries live — the registry loads
    through it, and the per-file validation and round-trip tests
    parametrize over it, so a new home (an army's magic items) joins
    everywhere at once.

    Returns:
        The YAML paths, sorted.
    """
    return sorted(
        (
            *data_dir.glob("tow/rules/*.yaml"),
            *data_dir.glob("tow/armies/*/magic-items/*.yaml"),
        )
    )


def _reconciled(loaded: Sequence[tuple[Path, Unit]]) -> list[Unit]:
    """The one datasheet per slug, from the several armies that may file it.

    Army membership is many-to-many — nine datasheets are fielded by more
    than one army, every one of them a mount or a beast — so a slug may
    arrive several times. Copies that agree *are* one datasheet and load as
    one; copies that disagree are a stale file, not a variant, since the
    game prints one Great Eagle however many armies take it.

    Agreement is on the parsed datasheet, never the bytes: the ``# Source:``
    header and any hand-authored comments differ freely, the game data may
    not.

    Returns:
        One unit per slug, in the order the paths were read.

    Raises:
        ValueError: two files carry the same slug but different datasheets.
            The message names both paths and the fields they disagree on.
    """
    reconciled: dict[str, tuple[Path, Unit]] = {}
    for path, unit in loaded:
        filed = reconciled.get(unit.id)
        if filed is None:
            reconciled[unit.id] = (path, unit)
            continue
        first_path, first = filed
        if first != unit:
            differing = ", ".join(
                field
                for field in type(unit).model_fields
                if getattr(first, field) != getattr(unit, field)
            )
            raise ValueError(
                f"unit {unit.id!r} differs between {first_path} and {path} "
                f"(on: {differing}); one copy is stale -- re-import both, or edit them to agree"
            )
    return [unit for _, unit in reconciled.values()]


class TOWRepository:
    """The hand-authored game data under ``data/``, loaded on demand.

    Every registry is a :class:`~avelorn.core.registry.Registry`:
    addressed by slug (``repo.weapons["longbow"]``) and resolving printed
    display names through ``by_name`` — the form a datasheet's
    ``equipment`` and ``special_rules`` strings take. Each registry loads
    once per instance.
    """

    def __init__(self, *, data_dir: Path = DATA_DIR) -> None:
        """Read game data from ``data_dir`` (the repo's ``data/`` by default)."""
        self._data_dir = data_dir

    @cached_property
    def units(self) -> Registry[Unit]:
        """Every army's roster, each datasheet's troop-type profile resolved.

        The datasheet prints its troop type as a name; loading resolves
        that against the troop-type table and attaches the profile, so a
        unit carries how it ranks up without a registry in hand later.

        A datasheet may be filed under every army that fields it — several
        do (a Unicorn is a High Elf, Bretonnian and Wood Elf mount alike) —
        so each army's directory stays complete and importing an army
        writes everything it fields. Those copies are reconciled here into
        the one datasheet they are (:func:`_reconciled`).
        """
        paths = sorted(self._data_dir.glob("tow/armies/*/units/*.yaml"))
        troop_types = self.troop_types
        loaded = [(path, load_yaml(path, Unit).with_troop_type(troop_types)) for path in paths]
        return Registry(_reconciled(loaded), kind="unit")

    @cached_property
    def weapons(self) -> Registry[Weapon]:
        """Weapon profiles."""
        return Registry(load_yaml_dir(self._data_dir / "tow/weapons", Weapon), kind="weapon")

    @cached_property
    def armoury(self) -> Registry[Armour]:
        """Armour items."""
        return Registry(load_yaml_dir(self._data_dir / "tow/armour", Armour), kind="armour")

    @cached_property
    def rules(self) -> Registry[Rule]:
        """Special rules, plus each army's magic items.

        A magic item lives under its army
        (``tow/armies/<army>/magic-items/``) but resolves through this one
        registry — an item's rule text compiles exactly like a special
        rule's until magic items earn a model of their own, and printed
        names are unique across both. :func:`rule_paths` states the homes.
        """
        entries = (load_yaml(path, Rule) for path in rule_paths(self._data_dir))
        return Registry(entries, kind="rule")

    @cached_property
    def troop_types(self) -> Registry[TroopTypeProfile]:
        """The troop-type table: each troop type's rank-and-file data."""
        loaded = load_yaml_dir(self._data_dir / "tow/troop-types", TroopTypeProfile)
        return Registry(loaded, kind="troop type")


_default_repository: "TOWRepository | None" = None


def default_repository() -> TOWRepository:
    """The process-wide default game data (the repo's ``data/`` tree).

    The ambient corpus for callers that do not thread their own — the
    ergonomic fielding entry point (:meth:`~avelorn.tow.contingent.Contingent.of`)
    resolves a slug against this when no ``data`` is injected. Built once and
    reused (each registry still loads lazily on first access); tests and
    alternate/doctored data pass their own :class:`TOWRepository` instead of
    touching this.

    Returns:
        The shared default repository.
    """
    global _default_repository  # the one process-wide default, built once
    if _default_repository is None:
        _default_repository = TOWRepository()
    return _default_repository
