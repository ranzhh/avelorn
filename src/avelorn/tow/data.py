"""Locating and loading the hand-authored game data under ``data/``.

``data/`` is the single source of truth — armies (and their units), weapons,
armour, and rules. :class:`TOWRepository` is the one place that knows the
tree's layout, so tests, demos, and the app read through it.
"""

from functools import cached_property
from pathlib import Path

from avelorn.core.loading import load_yaml, load_yaml_dir
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon

# data/ sits at the repository root, beside src/. Located from this file so the
# path holds regardless of the caller's working directory.
DATA_DIR = Path(__file__).parents[3] / "data"


class TOWRepository:
    """The hand-authored game data under ``data/``, loaded on demand.

    Two keys are in play, by role. **Units and weapons are addressed by slug**
    — which datasheet, which weapon to wield — so those registries are
    slug-keyed. **Armour and rules are resolved by the engine** against a
    unit's printed ``equipment`` and ``special_rules`` strings, so those are
    keyed by display name, the form those strings take in the data. Each
    registry loads once per instance.
    """

    def __init__(self, *, data_dir: Path = DATA_DIR) -> None:
        """Read game data from ``data_dir`` (the repo's ``data/`` by default)."""
        self._data_dir = data_dir

    @cached_property
    def units(self) -> dict[str, Unit]:
        """Every army's roster, keyed by slug (slugs are unique across armies)."""
        paths = sorted(self._data_dir.glob("tow/armies/*/units/*.yaml"))
        return {path.stem: load_yaml(path, Unit) for path in paths}

    @cached_property
    def weapons(self) -> dict[str, Weapon]:
        """Weapon profiles, keyed by slug."""
        paths = sorted((self._data_dir / "tow/weapons").glob("*.yaml"))
        return {path.stem: load_yaml(path, Weapon) for path in paths}

    @cached_property
    def armoury(self) -> dict[str, Armour]:
        """Armour, keyed by display name — how the engine resolves equipment strings."""
        return {a.name: a for a in load_yaml_dir(self._data_dir / "tow/armour", Armour)}

    @cached_property
    def rules(self) -> dict[str, Rule]:
        """Special rules, keyed by display name — how the engine resolves rule names."""
        return {r.name: r for r in load_yaml_dir(self._data_dir / "tow/rules", Rule)}
