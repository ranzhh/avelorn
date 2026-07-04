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
        """Every army's roster (unit slugs are unique across armies)."""
        paths = sorted(self._data_dir.glob("tow/armies/*/units/*.yaml"))
        return Registry((load_yaml(path, Unit) for path in paths), kind="unit")

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
