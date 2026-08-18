"""Each seat of an attack, resolved once and shared by both phases.

A strike and a volley resolve the same two seats: the attacker's
(:class:`Offence`) compiles the weapon profile in use and the striker's
own unit rules into the walk and gathers its re-roll grants; the
target's (:class:`Defence`) folds its armour, the ward its rules grant,
its own re-rolls and its enemy-subject maluses — each gated on that
side's own facts.

The seats only *report* their factored and inapplicable names. Which of
them a resolution may claim out of the "not factored" notes differs by
who resolves what — a one-sided strike leaves the striker's own defence
noted, a full round claims both walks' both seats — so claiming stays
with the phases. Engine-pure: constructors take the resolved loadout's
parts, never the on-field Contingent.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from avelorn.tow.engine.armour import defender_armour
from avelorn.tow.engine.attack import Modifier
from avelorn.tow.engine.rules import (
    EffectiveRerolls,
    EffectiveValue,
    EffectiveWard,
    GateContext,
    compile_rules,
    effective_armour_value,
    effective_rerolls,
    effective_ward_target,
)
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.weapon import WeaponProfile


@dataclass(frozen=True)
class Offence:
    """The attacker's seat of one walk: what its rules put on the dice.

    ``modifiers`` is the weapon profile's compiled rules then the unit's
    own, in walk order. ``rerolls`` are the unit rules' re-roll grants and
    ``weapon_rerolls`` the profile-in-use's — per source, so a printed
    name shared across the two namespaces cannot claim the other's note.
    ``weapon_unfactored`` are the weapon rules the walk could not factor;
    the caller filters them against what its other seams claimed (the
    attack count, the Initiative read, the shot count) before noting.
    """

    modifiers: tuple[Modifier, ...]
    rerolls: EffectiveRerolls
    weapon_rerolls: EffectiveRerolls
    factored: frozenset[str]
    inapplicable: frozenset[str]
    weapon_unfactored: tuple[str, ...]

    @classmethod
    def resolve(
        cls,
        profile: WeaponProfile,
        *,
        weapon_rules: Mapping[str, Rule],
        rules: Sequence[Rule],
        grants: Mapping[str, Rule],
        conditions: "GateContext | None" = None,
    ) -> "Offence":
        """Resolve an attacker's seat: its weapon profile and unit rules, gated.

        Returns:
            The seat, compiled under the attacker's ``conditions``.
        """
        weapon_compiled = compile_rules(profile.special_rules, weapon_rules, conditions)
        index = {rule.name: rule for rule in rules}
        unit_compiled = compile_rules(list(index), index, conditions, grants=grants)
        in_use = [weapon_rules[name] for name in profile.special_rules if name in weapon_rules]
        return cls(
            modifiers=(*weapon_compiled.modifiers, *unit_compiled.modifiers),
            rerolls=effective_rerolls(rules, conditions, seat=Side.ATTACKER),
            weapon_rerolls=effective_rerolls(in_use, conditions, seat=Side.ATTACKER),
            factored=frozenset(unit_compiled.factored),
            inapplicable=frozenset(unit_compiled.inapplicable),
            weapon_unfactored=(*weapon_compiled.unfactored, *weapon_compiled.inapplicable),
        )


@dataclass(frozen=True)
class Defence:
    """The target's seat of one walk: everything its own rules do about it.

    ``armour_value`` is the worn armour folded and rule-improved, None for
    an unarmoured target; ``armour`` is that fold's full report. ``ward``
    is the best ward the rules grant against this attack, its own seam
    after the armour save. ``modifiers`` are the enemy-subject maluses on
    the striker's dice, ``rerolls`` the target's own.
    """

    armour_value: int | None
    armour: EffectiveValue
    ward: EffectiveWard
    modifiers: tuple[Modifier, ...]
    rerolls: EffectiveRerolls
    factored: frozenset[str]
    inapplicable: frozenset[str]

    @classmethod
    def resolve(
        cls,
        *,
        armour: Sequence[Armour],
        rules: Sequence[Rule],
        grants: Mapping[str, Rule],
        incoming: "GateContext | None" = None,
    ) -> "Defence":
        """Resolve a target's seat against an incoming attack.

        Every fold runs even for a bare target — each is the seam that
        owns its rules' disposition, and skipping one would leave a rule
        unspoken for.

        Returns:
            The seat, folded under the target's ``incoming`` facts.
        """
        printed = defender_armour(armour)
        armour_fold = effective_armour_value(printed, rules, incoming)
        index = {rule.name: rule for rule in rules}
        compiled = compile_rules(list(index), index, incoming, seat=Side.TARGET, grants=grants)
        return cls(
            armour_value=None if printed is None else armour_fold.value,
            armour=armour_fold,
            ward=effective_ward_target(rules, incoming),
            modifiers=tuple(compiled.modifiers),
            rerolls=effective_rerolls(rules, incoming, seat=Side.TARGET),
            factored=frozenset(compiled.factored),
            inapplicable=frozenset(compiled.inapplicable),
        )
