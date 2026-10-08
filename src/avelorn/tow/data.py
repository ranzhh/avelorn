"""Locating and loading the hand-authored game data under ``data/``.

``data/`` is the single source of truth — armies (and their units),
weapons, armour, rules, and the ledger of what the engine leaves unmodelled.
:class:`TOWRepository` is the one place that knows the tree's layout, so tests,
demos, and the app read through it.
"""

from collections.abc import Iterable, Mapping, Sequence
from functools import cached_property
from pathlib import Path

from avelorn.core.loading import load_yaml, load_yaml_dir
from avelorn.core.registry import Registry
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.effect import Effect, FactRef, conflicts
from avelorn.tow.schema.ledger import Ledger
from avelorn.tow.schema.program import DerivedFact, FactType, StateFact, StateFile
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import GrantEffect, Rule, bind
from avelorn.tow.schema.step import Step
from avelorn.tow.schema.troop_type import TroopTypeProfile
from avelorn.tow.schema.unit import Characteristic, Unit
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


def _checked(where: str, references: Iterable[RuleRef], rules: Mapping[str, Rule]) -> None:
    """Fail the load on a reference that names no rule or does not bind its X.

    Raises:
        ValueError: naming the entry, the reference and what its rule expects.
    """
    for reference in references:
        try:
            bind(reference, rules)
        except ValueError as err:
            raise ValueError(f"{where}: {reference}: {err}") from err


def _addressed(rules: Mapping[str, Rule], state: Iterable[StateFact]) -> None:
    """Fail the load on a rule whose effects the graph cannot read as written.

    Raises:
        ValueError: naming the rule and what the graph cannot read.
    """
    types = {fact.fact: fact.type for fact in state}
    types |= {str(fact): FactType.INT for fact in (*DerivedFact, *Characteristic)}
    known = {*types, *Step}
    for rule in rules.values():
        if rule.effects and rule.graph is None:
            raise ValueError(f"rule {rule.id}: its effects state no addresses")
        for effect in () if rule.graph is None else rule.graph.effects:
            if unknown := sorted(effect.facts - known):
                raise ValueError(f"rule {rule.id}: no fact is named {', '.join(unknown)}")
            if missing := sorted(effect.rules - set(rules)):
                raise ValueError(f"rule {rule.id}: no rule entry {', '.join(missing)}")
            _typed(rule.id, effect, types)
    graphs = {slug: rule.graph.effects for slug, rule in rules.items() if rule.graph is not None}
    if found := conflicts(graphs):
        raise ValueError("; ".join(found))


def _typed(rule: str, effect: Effect, types: Mapping[str, FactType]) -> None:
    """Fail the load on a fact read against the type ``state.yaml`` gives it.

    Raises:
        ValueError: naming the rule and the fact.
    """
    for read in (*effect.fact_gates, *effect.fact_refs):
        if read.fact in types and read.of is None:
            raise ValueError(f"rule {rule}: {read.fact} is read without of")
    for ref in effect.amounts:
        if isinstance(ref, FactRef) and types.get(ref.fact, FactType.INT) is not FactType.INT:
            raise ValueError(f"rule {rule}: {ref.fact} is no number")
    for gate in effect.fact_gates:
        comparator, value = gate.compared
        kind = types.get(gate.fact)
        if kind is not None and not _fits(kind, comparator, value, types):
            written = f"{comparator} {value!r}"
            raise ValueError(f"rule {rule}: {gate.fact} ({kind}) cannot be compared {written}")


def _fits(kind: FactType, comparator: str, value: object, types: Mapping[str, FactType]) -> bool:
    if isinstance(value, FactRef):
        return types.get(value.fact, kind) is kind and kind is FactType.INT
    if kind is FactType.BOOL:
        return comparator == "is" and isinstance(value, bool)
    return kind is FactType.INT and isinstance(value, int) and not isinstance(value, bool)


def _named(kind: str, names: Iterable[tuple[str, frozenset[str]]], known: Iterable[str]) -> None:
    """Fail the load on a rule naming a weapon or armour that has no entry.

    Raises:
        ValueError: naming the rule and what it names.
    """
    entries = set(known)
    for rule, named in names:
        if missing := sorted(named - entries):
            raise ValueError(f"rule {rule}: no {kind} entry {', '.join(missing)}")


class TOWRepository:
    """The hand-authored game data under ``data/``, loaded on demand.

    Every registry is a :class:`~avelorn.core.registry.Registry`:
    addressed by slug (``repo.weapons["longbow"]``) and resolving printed
    display names through ``by_name`` — the form a datasheet's
    ``equipment`` strings take. Each registry loads once per instance, and
    every rule reference it holds is bound against the rules as it loads.
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
        units = Registry(_reconciled(loaded), kind="unit")
        for unit in units.values():
            options = [(*o.adds_rules, *o.removes_rules) for o in unit.options]
            references = [*unit.special_rules, *(ref for refs in options for ref in refs)]
            _checked(f"unit {unit.id}", references, self.rules)
        return units

    @cached_property
    def fielded_by(self) -> Mapping[str, tuple[str, ...]]:
        """Which armies file each datasheet, by unit slug.

        The army is the directory a datasheet sits in rather than anything
        the YAML declares, so it is read off the path here and nowhere else.
        A slug maps to every army that fields it, sorted.

        Returns:
            One entry per unit slug, each the army slugs filing it.
        """
        filed: dict[str, set[str]] = {}
        for path in self._data_dir.glob("tow/armies/*/units/*.yaml"):
            filed.setdefault(path.stem, set()).add(path.parents[1].name)
        return {slug: tuple(sorted(armies)) for slug, armies in sorted(filed.items())}

    @cached_property
    def weapons(self) -> Registry[Weapon]:
        """Weapon profiles."""
        weapons = Registry(load_yaml_dir(self._data_dir / "tow/weapons", Weapon), kind="weapon")
        for weapon in weapons.values():
            references = [ref for profile in weapon.profiles for ref in profile.special_rules]
            _checked(f"weapon {weapon.id}", references, self.rules)
        named = [(slug, e.weapons) for slug, rule in self.rules.items() for e in _effects(rule)]
        _named("weapon", named, weapons)
        return weapons

    @cached_property
    def armoury(self) -> Registry[Armour]:
        """Armour items."""
        armoury = Registry(load_yaml_dir(self._data_dir / "tow/armour", Armour), kind="armour")
        named = [(slug, e.armour) for slug, rule in self.rules.items() for e in _effects(rule)]
        _named("armour", named, armoury)
        held = [(slug, e.held) for slug, rule in self.rules.items() for e in _effects(rule)]
        _named("weapon or armour", held, {*self.weapons, *armoury})
        return armoury

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
        rules = Registry(entries, kind="rule")
        for rule in rules.values():
            grants = [e.grants for e in rule.effects if isinstance(e, GrantEffect)]
            grants += [e.grants for e in _effects(rule) if e.grants is not None]
            _checked(f"rule {rule.id}", grants, rules)
        state = load_yaml(self._data_dir / "tow/state.yaml", StateFile)
        _addressed(rules, state.facts)
        return rules

    @cached_property
    def troop_types(self) -> Registry[TroopTypeProfile]:
        """The troop-type table: each troop type's rank-and-file data."""
        loaded = load_yaml_dir(self._data_dir / "tow/troop-types", TroopTypeProfile)
        troop_types = Registry(loaded, kind="troop type")
        for troop_type in troop_types.values():
            _checked(f"troop type {troop_type.id}", troop_type.special_rules, self.rules)
        return troop_types

    @cached_property
    def ledger(self) -> Ledger:
        """The gaps between the corpus and the engine, each acknowledged with a reason."""
        return load_yaml(self._data_dir / "tow/unmodelled.yaml", Ledger)


def _effects(rule: Rule) -> tuple[Effect, ...]:
    return () if rule.graph is None else rule.graph.effects


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
