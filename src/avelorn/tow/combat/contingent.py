"""A unit as fielded on the table, and the record of a charge move.

The gameplay-side counterpart of the army-list layer
(:mod:`avelorn.tow.muster`): a :class:`Contingent` is the body the combat
resolvers take — a datasheet plus the models actually standing.
:class:`Charge` records a charge move — event data, carried by the
action that resolves it (:func:`~avelorn.tow.combat.charge.charge`, via
the :class:`~avelorn.tow.combat.context.CombatContext`), never by the
unit. Fielding is also where printed names stop being strings:
:meth:`Contingent.deploy` resolves equipment and special rules into a
:class:`Loadout`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from avelorn.core.registry import Registry
from avelorn.tow.combat.rules import printed_rule
from avelorn.tow.muster import Complement
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon


@dataclass(frozen=True)
class Loadout:
    """A contingent's gear and rules resolved to entries, at fielding time.

    Built at :meth:`Contingent.deploy` — the muster boundary is where a
    printed name stops being a string. The armour is what save resolution
    will read; the weapons are what a per-action choice will pick from;
    ``rules`` are the unit's special rules that resolve against the rule
    data — each the rule exactly as printed, parameters substituted, by
    the engine's one resolution convention
    (:func:`~avelorn.tow.combat.rules.printed_rule`).

    The two halves miss differently, by design. Equipment coverage is
    complete, so an unresolvable equipment name fails the deploy. Rule
    entries exist only for what the engine can honour, so a rule without
    one is the norm — unit rules without entries ride along printed, in
    :attr:`unresolved_rules`, and keep feeding the "not factored" notes
    rather than silently vanishing, and a weapon-rule name absent from
    :attr:`weapon_rules` compiles to unfactored the same way.
    """

    weapons: tuple[Weapon, ...]
    armour: tuple[Armour, ...]
    rules: tuple[Rule, ...]
    unresolved_rules: tuple[str, ...]
    # Every rule name printed on a carried weapon's profiles that has an
    # entry, resolved as printed — the per-action compile looks names up
    # here instead of in a registry. Names without entries are simply
    # absent and compile to unfactored, as ever.
    weapon_rules: Mapping[str, Rule] = field(default_factory=dict)

    def weapon(self, name: str) -> Weapon:
        """The carried weapon with the given printed name.

        The text boundary's resolver: a CLI argument or an API request
        names the weapon, this turns it into the entry once, and the
        engine works with the object from there
        (:meth:`Contingent.wields` confirms it is carried).

        Returns:
            The carried weapon entry.

        Raises:
            ValueError: no carried weapon has that name — a unit fights
                with what it carries.
        """
        for weapon in self.weapons:
            if weapon.name == name:
                return weapon
        carried = ", ".join(weapon.name for weapon in self.weapons) or "nothing"
        raise ValueError(f"no {name!r} in this loadout; carried: {carried}")


class ChargeArc(StrEnum):
    """Which arc a charge struck.

    The rulebook caps the charge Initiative bonus per arc (front vs flank
    or rear), but flank and rear diverge elsewhere — the combat-result
    bonuses each grants differ (#28) — so all three are distinguished
    here, and each arc carries its own printed numbers.
    """

    FRONT = "front"
    FLANK = "flank"
    REAR = "rear"

    @property
    def initiative_cap(self) -> int:
        """The arc's cap on the charge Initiative bonus.

        Returns:
            +3 into the front arc, +4 into the flank or rear
            (the-combat-phase/charging-units).
        """
        return 3 if self is ChargeArc.FRONT else 4


@dataclass(frozen=True)
class Charge:
    """A charge move: how far it carried, into which arc. A pure record.

    Both facts are read by the rules the charge feeds — the Combat-phase
    Initiative bonus computes in
    :func:`~avelorn.tow.combat.melee.effective_initiative`, and the
    flank/rear combat-result bonuses are a still-deferred concern (#28).
    The arc has no default: which arc a charge struck is a fact of the
    move, not a parameter to assume.
    """

    full_inches: int
    arc: ChargeArc

    def __post_init__(self) -> None:
        """Reject a nonsensical move.

        Raises:
            ValueError: the charge distance is negative — a programming
                error, not a zero bonus.
        """
        if self.full_inches < 0:
            raise ValueError(f"a charge cannot move a negative distance ({self.full_inches})")


@dataclass(frozen=True)
class Contingent:
    """A unit as fielded: its datasheet and the models on the table.

    The datasheet (:class:`~avelorn.tow.schema.unit.Unit`) is a template —
    it carries the *allowed* size, not how many models stand on the table —
    so ``models`` supplies the fielded count. Nothing about the turn rides
    here: a charge is an action's event data
    (:class:`~avelorn.tow.combat.context.CombatContext`), not unit state.

    Two constructors resolve a loadout at the muster boundary.
    :meth:`deploy` fields a mustered list entry — a
    :class:`~avelorn.tow.muster.Complement` (list-legal size, chosen
    options), its loadout baked into the datasheet the engine reads.
    :meth:`field` fields a bare datasheet at its printed, optionless
    default — any model count, so a remnant or an isolated what-if needs
    no legal list size. The raw constructor is for bodies whose loadout
    already exists: a post-casualty remnant is
    ``dataclasses.replace(contingent, models=survivors)``.

    The weapon in use is *not* carried here: it is a per-action choice, so
    the same contingent shoots with its bow one moment and fights the
    ensuing melee with a hand weapon the next. Each action takes the chosen
    weapon (:func:`~avelorn.tow.combat.melee.fight`,
    :func:`~avelorn.tow.combat.charge.stand_and_shoot`).

    Today a contingent is a single homogeneous body — one profile (the
    rank-and-file, ``unit.profiles[0]``). A real contingent can be
    heterogeneous: rank and file plus a champion, plus an embedded
    character, each its own profile, Attacks and weapon. That is
    deliberately not modelled yet (#46); when it is, this grows a notion of
    *parts* and the single-body fields become the one-part case. Callers read
    only ``profiles[0]``, so the assumption stays localized to that migration.
    """

    unit: Unit
    models: int
    loadout: Loadout

    def wields(self, weapon: Weapon) -> Weapon:
        """The weapon, confirmed carried: a unit fights with what it has.

        Every action's weapon choice passes through here, so an
        arbitrary entry cannot be fought with — only what was fielded.

        Returns:
            The same weapon, when the loadout carries it.

        Raises:
            ValueError: the loadout does not carry it.
        """
        if weapon not in self.loadout.weapons:
            carried = ", ".join(w.name for w in self.loadout.weapons) or "nothing"
            raise ValueError(
                f"{self.unit.name} does not carry {weapon.name!r}; carried: {carried}"
            )
        return weapon

    @classmethod
    def deploy(
        cls,
        complement: Complement,
        *,
        weapons: Registry[Weapon],
        armoury: Registry[Armour],
        rules: Registry[Rule],
    ) -> "Contingent":
        """Field a :class:`~avelorn.tow.muster.Complement`, resolving its equipment.

        The complement's chosen loadout — its equipment and special rules
        after its options' adds and removes — is baked into the datasheet the
        engine reads, so the contingent fights with what was bought, not the
        printed profile; the chosen ``size`` becomes ``models``. The printed
        names also resolve into a :class:`Loadout`, each kind on its own
        terms: an equipment name matching no weapon or armour entry is an
        error — coverage is complete (a test pins it), so a miss here is a
        typo in the list, and the human building the list is the one to
        tell — while a special rule without an entry is expected (entries
        exist only for what the engine can honour) and rides along printed.

        Args:
            complement: The list entry to field.
            weapons: Weapon entries, resolving printed equipment names.
            armoury: Armour entries, resolving printed equipment names.
            rules: Rule entries, resolving printed special-rule names.

        Returns:
            The fielded contingent, loadout resolved.

        Raises:
            ValueError: a piece of equipment matches no weapon or armour
                entry.
        """
        fielded = complement.unit.model_copy(
            update={
                "equipment": complement.equipment,
                "special_rules": complement.special_rules,
            }
        )
        loadout, unknown = _resolve_loadout(fielded, weapons=weapons, armoury=armoury, rules=rules)
        if unknown:
            raise ValueError(f"{fielded.name}: equipment matches no weapon or armour: {unknown}")
        return cls(fielded, complement.size, loadout)

    @classmethod
    def field(
        cls,
        unit: Unit,
        models: int,
        *,
        weapons: Registry[Weapon],
        armoury: Registry[Armour],
        rules: Registry[Rule],
    ) -> "Contingent":
        """Field a bare datasheet at its printed, optionless loadout.

        The default per unit: no options chosen, the printed equipment
        and special rules resolved exactly as :meth:`deploy` resolves a
        list entry's. ``models`` is any count — a remnant or an isolated
        what-if needs no legal list size, which is why this does not
        route through a :class:`~avelorn.tow.muster.Complement`.

        Args:
            unit: The datasheet to field.
            models: The models on the table.
            weapons: Weapon entries, resolving printed equipment names.
            armoury: Armour entries, resolving printed equipment names.
            rules: Rule entries, resolving printed special-rule names.

        Returns:
            The fielded contingent, loadout resolved.

        Raises:
            ValueError: a piece of equipment matches no weapon or armour
                entry.
        """
        loadout, unknown = _resolve_loadout(unit, weapons=weapons, armoury=armoury, rules=rules)
        if unknown:
            raise ValueError(f"{unit.name}: equipment matches no weapon or armour: {unknown}")
        return cls(unit, models, loadout)


def _resolve_loadout(
    unit: Unit,
    *,
    weapons: Registry[Weapon],
    armoury: Registry[Armour],
    rules: Registry[Rule],
) -> tuple[Loadout, list[str]]:
    # The muster-boundary resolution both constructors share: equipment
    # partitions into weapons and armour, special rules resolve where
    # entries exist and ride along printed where they do not. Unknown
    # equipment comes back for the constructor to refuse — coverage is
    # complete, so a miss is a typo in the list.
    wielded, rest = weapons.resolve(unit.equipment)
    worn, unknown = armoury.resolve(rest)
    resolved: list[Rule] = []
    unresolved: list[str] = []
    for printed in unit.special_rules:
        entry = printed_rule(printed, rules)
        if entry is None:
            unresolved.append(printed)
        else:
            resolved.append(entry)
    weapon_rules: dict[str, Rule] = {}
    for weapon in wielded:
        for profile in weapon.profiles:
            for printed in profile.special_rules:
                if printed not in weapon_rules and (entry := printed_rule(printed, rules)):
                    weapon_rules[printed] = entry
    loadout = Loadout(
        tuple(wielded), tuple(worn), tuple(resolved), tuple(unresolved), weapon_rules
    )
    return loadout, unknown
