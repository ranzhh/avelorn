"""Locating and loading the hand-authored game data under ``data/``.

``data/`` is the single source of truth — armies (and their units),
weapons, armour, and rules. :class:`TOWRepository` is the one place that
knows the tree's layout, so tests, demos, and the app read through it.
"""

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
        """
        paths = sorted(self._data_dir.glob("tow/armies/*/units/*.yaml"))
        troop_types = self.troop_types
        units = (load_yaml(path, Unit).with_troop_type(troop_types) for path in paths)
        return Registry(units, kind="unit")

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
        """Special rules."""
        return Registry(load_yaml_dir(self._data_dir / "tow/rules", Rule), kind="rule")

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
