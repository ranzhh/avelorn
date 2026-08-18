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
from avelorn.tow.engine.attack import Modifier, Transform
from avelorn.tow.engine.rules import (
    EffectiveMarks,
    EffectiveRerolls,
    EffectiveValue,
    EffectiveWard,
    GateContext,
    attack_marks,
    barred_worn,
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
    ``marks`` is what the attacks *are* — magical, Flaming — read from the
    same two sources (:func:`~avelorn.tow.engine.rules.attack_marks`); the
    consumed rules are already claimed out of ``factored`` and
    ``weapon_unfactored``, so a mark in the facts is never also reported
    unfactored.
    """

    modifiers: tuple[Modifier, ...]
    # The bespoke hooks the compiles emitted beside the records — a blow's
    # save denial and escalation — weapon profile's first, unit's after,
    # matching the modifiers' order.
    transforms: tuple[Transform, ...]
    rerolls: EffectiveRerolls
    weapon_rerolls: EffectiveRerolls
    factored: frozenset[str]
    inapplicable: frozenset[str]
    weapon_unfactored: tuple[str, ...]
    marks: EffectiveMarks

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
        marks = attack_marks(profile.special_rules, weapon_rules, rules)
        return cls(
            modifiers=(*weapon_compiled.modifiers, *unit_compiled.modifiers),
            transforms=(*weapon_compiled.transforms, *unit_compiled.transforms),
            rerolls=effective_rerolls(rules, conditions, seat=Side.ATTACKER),
            weapon_rerolls=effective_rerolls(in_use, conditions, seat=Side.ATTACKER),
            factored=frozenset({*unit_compiled.factored, *marks.unit_factored}),
            inapplicable=frozenset(unit_compiled.inapplicable),
            weapon_unfactored=tuple(
                name
                for name in (*weapon_compiled.unfactored, *weapon_compiled.inapplicable)
                if name not in marks.weapon_factored
            ),
            marks=marks,
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
    # The rules of the target's own weapon in use this seat consumed — a
    # two-handed weapon denying the shield (Requires Two Hands), a magic
    # weapon warding its wielder. A weapon-rule namespace of its own, so the
    # bearer's weapon notes claim these, never the unit-rule notes.
    weapon_factored: frozenset[str] = frozenset()

    @classmethod
    def resolve(
        cls,
        *,
        armour: Sequence[Armour],
        rules: Sequence[Rule],
        grants: Mapping[str, Rule],
        incoming: "GateContext | None" = None,
        weapon_rules_in_use: Sequence[Rule] = (),
    ) -> "Defence":
        """Resolve a target's seat against an incoming attack.

        Every fold runs even for a bare target — each is the seam that
        owns its rules' disposition, and skipping one would leave a rule
        unspoken for. The unit's rules fold first and the weapon in use's
        (``weapon_rules_in_use`` — Requires Two Hands lives there) on the
        result, each in its own claim namespace; wards never stack, so the
        best of the two sources' grants applies.

        Returns:
            The seat, folded under the target's ``incoming`` facts.
        """
        # A barred piece (Requires Two Hands' shield, in combat) is withdrawn
        # from what the target effectively wears before any value is read —
        # its bonus goes with it whole, whatever its size.
        barred = barred_worn(weapon_rules_in_use, incoming)
        usable = [piece for piece in armour if piece.name not in barred.names]
        printed = defender_armour(usable)
        unit_fold = effective_armour_value(printed, rules, incoming)
        after_unit = None if printed is None else unit_fold.value
        weapon_fold = effective_armour_value(after_unit, weapon_rules_in_use, incoming)
        unit_ward = effective_ward_target(rules, incoming)
        weapon_ward = effective_ward_target(weapon_rules_in_use, incoming)
        granted = [t for t in (unit_ward.target, weapon_ward.target) if t is not None]
        index = {rule.name: rule for rule in rules}
        compiled = compile_rules(list(index), index, incoming, seat=Side.TARGET, grants=grants)
        return cls(
            armour_value=None if printed is None else weapon_fold.value,
            armour=EffectiveValue(weapon_fold.value, unit_fold.factored, unit_fold.unfactored),
            ward=EffectiveWard(
                min(granted) if granted else None, unit_ward.factored, unit_ward.unfactored
            ),
            modifiers=tuple(compiled.modifiers),
            rerolls=effective_rerolls(rules, incoming, seat=Side.TARGET),
            inapplicable=frozenset(compiled.inapplicable),
            factored=frozenset(compiled.factored),
            weapon_factored=frozenset(
                {*weapon_fold.factored, *weapon_ward.factored, *barred.factored}
            ),
        )
