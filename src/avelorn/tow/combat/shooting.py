"""The shooting attack chain: hit, wound, armour save, ward save.

Targets are treated as a unit of identical models with a shared Wounds
value; unsaved wounds accumulate into whole slain models (carry-over
within the unit), and casualties cap at the unit's size. Heterogeneous
units (e.g. a champion with a different profile) still resolve off the
rank-and-file profile only. Anything the math cannot honour (special
rules, unrecognised equipment) is reported in ``ShootingResult.notes``
rather than silently ignored.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from avelorn.core.dice import (
    binomial_distribution,
    cap_distribution,
    expected_value,
    group_distribution,
    multinomial_outcomes,
)
from avelorn.tow.combat.attack import (
    AttackProfile,
    Outcome,
    RollState,
    RollTarget,
    Transform,
    resolve_attack,
)
from avelorn.tow.combat.charts import (
    BEST_ARMOUR_VALUE,
    UNARMOURED,
    armour_save_target,
    hit_probability,
    save_probability,
    shooting_hit_target,
    wound_probability,
    wound_target,
)
from avelorn.tow.combat.context import EngagementContext
from avelorn.tow.combat.rules import compile_rules
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon

logger = logging.getLogger(__name__)

# Rules filed under the shooting phase chapter apply to every volley.
_SHOOTING_PHASE = "The Shooting Phase"


@dataclass(frozen=True)
class ShootingResult:
    """Outcome of a volley of shooting attacks against a unit."""

    shots: int
    hit_target: int
    wound_target: int | None
    save_target: int | None
    ward_target: int | None
    p_hit: float
    p_wound: float
    p_unsaved: float  # per-shot probability of an unsaved wound
    distribution: list[float]  # index k = P(exactly k unsaved wounds)
    casualties: list[float]  # index k = P(exactly k models removed)
    notes: tuple[str, ...] = ()
    target_models: int | None = None  # size of the target unit, if bounded

    @property
    def expected_wounds(self) -> float:
        """Mean number of unsaved wounds.

        Returns:
            The expectation of the wound distribution.
        """
        return expected_value(self.distribution)

    @property
    def expected_casualties(self) -> float:
        """Mean number of models removed, capped at the target unit's size.

        Equals :attr:`expected_wounds` for a 1-Wound target large enough to
        absorb every wound; it is lower only when the volley would overkill
        the unit.

        Returns:
            The expectation of the casualty distribution.
        """
        return expected_value(self.casualties)


def shoot(
    shots: int,
    ballistic_skill: int,
    strength: int,
    toughness: int,
    *,
    armour_value: int | None = None,
    armour_piercing: int = 0,
    ward_target: int | None = None,
    hit_modifier: int = 0,
    wounds_per_model: int = 1,
    targets: int | None = None,
    transforms: Sequence[Transform] = (),
    notes: tuple[str, ...] = (),
) -> ShootingResult:
    """Resolve a volley of identical shooting attacks probabilistically.

    ``wounds_per_model`` is the target's Wounds: unsaved wounds accumulate
    into whole slain models (three wounds fell one Ogre), with leftover
    wounds sitting on a survivor; an instant kill removes a model outright
    regardless of its Wounds. ``targets`` is the number of models in the
    unit; when given, casualties cap at it — a volley cannot remove more
    models than the unit contains. The unsaved-wound ``distribution`` is
    unaffected by either; it never depends on the receiving unit.

    ``transforms`` are rule hooks applied to each attack's dice walk —
    the seam the rules compiler will wire; nothing in production passes
    any yet.

    Returns:
        The per-shot probabilities, the distribution of unsaved wounds, and
        the casualty (models-removed) distribution.

    Raises:
        ValueError: `shots` is negative, `targets` is negative, or
            `wounds_per_model` is less than 1.
    """
    if shots < 0:
        raise ValueError("shots must be >= 0")
    if targets is not None and targets < 0:
        raise ValueError("targets must be >= 0")
    if wounds_per_model < 1:
        raise ValueError("wounds_per_model must be >= 1")

    hit = shooting_hit_target(ballistic_skill, hit_modifier)
    wound = wound_target(strength, toughness)
    save = armour_save_target(armour_value, armour_piercing)

    # The per-shot probabilities come from the exact dice walk; the chart
    # probabilities remain as the reported per-stage figures. The charts
    # speak the printed convention (None for "-"/no save); the walk speaks
    # roll states — converted here.
    resolution = resolve_attack(
        AttackProfile(
            hit_target=hit,
            wound_target=_roll_target(wound),
            save_target=_roll_target(save),
            ward_target=_roll_target(ward_target),
        ),
        transforms,
    )
    p_unsaved = float(resolution.p_unsaved)
    p_kill = float(resolution.p_of(Outcome.INSTANT_KILL))
    p_hit = hit_probability(hit)
    p_wound = wound_probability(wound)
    logger.debug(
        "per-shot unsaved wound: p=%.3f = hit %.3f x wound %.3f x save-fail %.3f x ward-fail %.3f",
        p_unsaved,
        p_hit,
        p_wound,
        1.0 - save_probability(save),
        1.0 - save_probability(ward_target),
    )

    if p_kill == 0.0:
        # Single outcome class: the multinomial degenerates to the binomial,
        # so keep the established path. Fold unsaved wounds into slain
        # models by Wounds-per-model, then cap at the unit's size; for
        # 1-Wound targets the fold is a no-op.
        distribution = binomial_distribution(shots, p_unsaved)
        models = group_distribution(distribution, wounds_per_model)
        casualties = models if targets is None else cap_distribution(models, targets)
    else:
        distribution, casualties = _remove_casualties(
            shots,
            p_wound_only=p_unsaved - p_kill,
            p_kill=p_kill,
            wounds_per_model=wounds_per_model,
            targets=targets,
        )

    return ShootingResult(
        shots=shots,
        hit_target=hit,
        wound_target=wound,
        save_target=save,
        ward_target=ward_target,
        p_hit=p_hit,
        p_wound=p_wound,
        p_unsaved=p_unsaved,
        distribution=distribution,
        casualties=casualties,
        notes=notes,
        target_models=targets,
    )


def _roll_target(target: int | None) -> RollTarget:
    # The charts' printed convention: None means the roll is not taken
    # and cannot succeed ("-" on the wound chart; no save).
    return RollState.IMPOSSIBLE if target is None else target


def _remove_casualties(
    shots: int,
    *,
    p_wound_only: float,
    p_kill: float,
    wounds_per_model: int,
    targets: int | None,
) -> tuple[list[float], list[float]]:
    # Class-aware aggregation, named after the printed "Remove Casualties"
    # step: enumerate (wounds, instant kills) counts over the volley by
    # multinomial. A kill removes a model outright; plain wounds accumulate
    # by Wounds-per-model. The unsaved-wound distribution counts both
    # classes (a Killing Blow is still an unsaved wound).
    distribution = [0.0] * (shots + 1)
    size = shots if targets is None else targets
    casualties = [0.0] * (size + 1)
    for (n_wound, n_kill), mass in multinomial_outcomes(shots, (p_wound_only, p_kill)):
        distribution[n_wound + n_kill] += mass
        killed = min(n_kill + n_wound // wounds_per_model, size)
        casualties[killed] += mass
    return distribution, casualties


def shoot_unit(
    attacker: Unit,
    defender: Unit,
    shooters: int,
    weapon: Weapon,
    *,
    armoury: Mapping[str, Armour] | None = None,
    rules: Mapping[str, Rule] | None = None,
    context: EngagementContext | None = None,
    hit_modifier: int = 0,
    defenders: int | None = None,
) -> ShootingResult:
    """Resolve ``shooters`` models of ``attacker`` shooting ``weapon`` at ``defender``.

    One shot per model, using each unit's first (rank-and-file) profile
    and the weapon's missile profile. ``armoury`` maps printed equipment
    names to armour items; ``rules`` maps printed rule names to rule
    entries, whose effects compile into the dice walk. Anything either
    mapping does not resolve — and every unit special rule — is not
    factored into the math but listed in the result's notes.

    ``context`` is the engagement's situation (moved, distance); rules
    conditioned on facts it leaves unknown stay unfactored and noted.
    Rules whose category is the shooting phase chapter apply to every
    volley, gated by their conditions.

    ``defenders`` is the number of models actually fielded in the target
    unit — the schema models only the *allowed* size, not what is on the
    table, so the count is supplied here. When given, casualties cap at it.

    Returns:
        The shooting outcome.

    Raises:
        ValueError: if the weapon has no missile profile, the attacker
            profile has no Ballistic Skill, the defender profile has no
            Toughness, or the weapon shoots at the wielder's Strength and
            the attacker profile has none.
    """
    # TODO: profile selection is naive. A unit that bought a champion
    # shoots with the champion too (possibly at higher BS, e.g. an
    # archers' Sentinel at BS 5), and units with split profiles need
    # per-profile resolution with the volley combined. Requires a notion
    # of unit composition (which models are actually fielded), which the
    # schema does not have yet.
    profile = weapon.missile_profile
    if profile is None:
        raise ValueError(f"{weapon.name} has no missile profile; it cannot shoot")
    ballistic_skill = attacker.profiles[0].ballistic_skill
    toughness = defender.profiles[0].toughness
    if ballistic_skill is None:
        raise ValueError(f"{attacker.name} has no Ballistic Skill; it cannot shoot")
    if toughness is None:
        raise ValueError(f"{defender.name} has no Toughness; it cannot be wounded")

    wielder_strength = attacker.profiles[0].strength
    if profile.strength.is_relative and wielder_strength is None:
        raise ValueError(
            f"{weapon.name} shoots at the wielder's Strength, but {attacker.name} has none"
        )
    strength = profile.strength.resolve(wielder_strength or 0)
    logger.debug(
        "resolving %d %s (BS %d) shooting %s at %s (T %d), S %d AP %d",
        shooters,
        attacker.name,
        ballistic_skill,
        weapon.name,
        defender.name,
        toughness,
        strength,
        profile.armour_piercing,
    )

    armour_value, notes = _defender_armour(defender, armoury or {})
    for unit in (attacker, defender):
        notes.extend(
            f"special rule not factored: {rule} ({unit.name})" for rule in unit.special_rules
        )
    # The engagement facts, by condition-field name; None = unknown.
    # Long range is printed as "further away than half the weapon's
    # maximum range".
    at_long_range = None
    if context is not None and context.distance is not None and isinstance(profile.range, int):
        at_long_range = context.distance > profile.range / 2
    conditions = {
        "moved": context.moved if context is not None else None,
        "at_long_range": at_long_range,
    }

    # Weapon rules with compiled effects join the dice walk; the rest are
    # reported, exactly as before. Shooting-phase chapter rules (Firing
    # at Long Range, Moving and Shooting) apply to every volley.
    transforms, unfactored = compile_rules(profile.special_rules, rules or {}, conditions)
    notes.extend(f"weapon rule not factored: {rule} ({weapon.name})" for rule in unfactored)
    phase_rules = sorted(
        r.name for r in (rules or {}).values() if r.category == _SHOOTING_PHASE and r.effects
    )
    phase_transforms, phase_unfactored = compile_rules(phase_rules, rules or {}, conditions)
    transforms.extend(phase_transforms)
    notes.extend(f"core rule not factored: {name}" for name in phase_unfactored)
    if weapon.notes is not None:
        notes.append(f"weapon notes not factored ({weapon.name}): {weapon.notes}")

    # Wounds accumulate into whole slain models; a profile with no printed
    # Wounds ("-") is treated as a single-Wound model.
    defender_wounds = defender.profiles[0].wounds or 1
    if defenders is not None:
        notes.append("panic test at 25% casualties not modelled")

    return shoot(
        shots=shooters,
        ballistic_skill=ballistic_skill,
        strength=strength,
        toughness=toughness,
        armour_value=armour_value,
        armour_piercing=profile.armour_piercing,
        hit_modifier=hit_modifier,
        wounds_per_model=defender_wounds,
        targets=defenders,
        transforms=transforms,
        notes=tuple(notes),
    )


def _defender_armour(
    defender: Unit, armoury: Mapping[str, Armour]
) -> tuple[int | None, list[str]]:
    suit = UNARMOURED
    improvement = 0
    notes: list[str] = []
    for item in defender.equipment:
        armour = armoury.get(item)
        if armour is None:
            notes.append(f"equipment not factored: {item} ({defender.name})")
        elif armour.armour_value is not None:
            suit = min(suit, armour.armour_value)
        elif armour.armour_value_improvement is not None:
            improvement += armour.armour_value_improvement
    value = max(suit - improvement, BEST_ARMOUR_VALUE)
    return (value if value < UNARMOURED else None), notes
