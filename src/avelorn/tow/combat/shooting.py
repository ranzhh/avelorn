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
from collections.abc import Sequence
from dataclasses import dataclass
from typing import assert_never

from avelorn.core.dice import expected_value
from avelorn.core.registry import Registry
from avelorn.tow.combat.armour import defender_armour
from avelorn.tow.combat.attack import (
    AttackProfile,
    HitRoll,
    Outcome,
    Transform,
    resolve_attack,
    roll_target,
)
from avelorn.tow.combat.casualties import wound_and_casualties
from avelorn.tow.combat.charts import (
    armour_save_target,
    hit_probability,
    save_probability,
    shooting_hit_target,
    wound_probability,
    wound_target,
)
from avelorn.tow.combat.context import EngagementContext
from avelorn.tow.combat.rules import compile_rules
from avelorn.tow.muster import Contingent
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Condition, Rule
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.schema.weapon import Weapon, WeaponProfile

logger = logging.getLogger(__name__)

# Rules filed under the shooting phase chapter apply to every volley.
_SHOOTING_PHASE = "The Shooting Phase"

# Empty registries as defaults: resolution against them misses everything,
# so an omitted registry degrades to notes exactly like unknown entries do.
_NO_ARMOURY: Registry[Armour] = Registry(kind="armour")
_NO_RULES: Registry[Rule] = Registry(kind="rule")


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
            wound_target=roll_target(wound),
            save_target=roll_target(save),
            ward_target=roll_target(ward_target),
        ),
        transforms,
        hit_roll=HitRoll.SHOOTING,
    )
    p_unsaved = float(resolution.p_unsaved)
    p_kill = float(resolution.p_of(Outcome.INSTANT_KILL))
    # Report the walk's effective To Hit target (transforms included) so
    # the printed target matches the math; other stages keep chart values.
    if isinstance(resolution.hit_target, int):
        hit = resolution.hit_target
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

    distribution, casualties = wound_and_casualties(
        shots,
        p_unsaved=p_unsaved,
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


def _at_long_range(profile: WeaponProfile, context: EngagementContext | None) -> bool | None:
    # Whether the shot is at long range, "further away than half the
    # weapon's maximum range". Needs both a known distance and a numeric
    # weapon range; without them the band is unknown (None).
    if context is None or context.distance is None or not isinstance(profile.range, int):
        return None
    return context.distance > profile.range / 2


def _engagement_conditions(
    profile: WeaponProfile, context: EngagementContext | None, force_short_range: bool
) -> dict[Condition, bool | None]:
    # One fact per Condition member; None = unknown. The match is
    # exhaustive (assert_never), so a new member fails the type check —
    # and a drift-guard test — until it is answered here. A shot forced
    # short (a Stand & Shoot reaction) is never at long range.
    def fact(condition: Condition) -> bool | None:
        match condition:
            case Condition.MOVED:
                return context.moved if context is not None else None
            case Condition.AT_LONG_RANGE:
                return False if force_short_range else _at_long_range(profile, context)
            case unanswered:
                assert_never(unanswered)

    return {condition: fact(condition) for condition in Condition}


def shoot_unit(
    attacker: Contingent,
    defender: Contingent,
    weapon: Weapon,
    *,
    armoury: Registry[Armour] = _NO_ARMOURY,
    rules: Registry[Rule] = _NO_RULES,
    context: EngagementContext | None = None,
    hit_modifier: int = 0,
    force_short_range: bool = False,
) -> ShootingResult:
    """Resolve ``attacker`` shooting a volley of ``weapon`` at ``defender``.

    One shot per fielded model (``attacker.models``), using each side's
    first (rank-and-file) profile and the weapon's missile profile;
    casualties cap at the defender's fielded ``models``. To resolve a
    partial volley (only some models in range or sight), field the
    shooting subset as its own contingent. ``armoury`` maps printed
    equipment names to armour items; ``rules`` maps printed rule names to
    rule entries, whose effects compile into the dice walk. Anything
    either mapping does not resolve — and every unit special rule — is
    not factored into the math but listed in the result's notes.

    ``context`` is the engagement's situation (moved, distance); rules
    conditioned on facts it leaves unknown stay unfactored and noted.
    Rules whose category is the shooting phase chapter apply to every
    volley, gated by their conditions. ``force_short_range`` treats the
    shot as within half range whatever the distance — a Stand & Shoot
    reaction, exempt from Firing at Long Range, sets it so that rule is
    honoured as a no-op rather than left unknown and noted.

    Returns:
        The shooting outcome.

    Raises:
        ValueError: if the weapon has no missile profile, the attacker
            profile has no Ballistic Skill, the defender profile has no
            Toughness, or the weapon shoots at the wielder's Strength and
            the attacker profile has none.
    """
    shooters, defenders = attacker.models, defender.models
    shooter, target = attacker.unit, defender.unit
    # TODO: profile selection is naive. A unit that bought a champion
    # shoots with the champion too (possibly at higher BS, e.g. an
    # archers' Sentinel at BS 5), and units with split profiles need
    # per-profile resolution with the volley combined. Requires a notion
    # of unit composition (which models are actually fielded), which the
    # schema does not have yet.
    profile = weapon.missile_profile
    if profile is None:
        raise ValueError(f"{weapon.name} has no missile profile; it cannot shoot")
    ballistic_skill = shooter.profiles[0][Characteristic.BALLISTIC_SKILL]
    toughness = target.profiles[0][Characteristic.TOUGHNESS]
    if ballistic_skill is None:
        raise ValueError(f"{shooter.name} has no Ballistic Skill; it cannot shoot")
    if toughness is None:
        raise ValueError(f"{target.name} has no Toughness; it cannot be wounded")

    wielder_strength = shooter.profiles[0][Characteristic.STRENGTH]
    if profile.strength.is_relative and wielder_strength is None:
        raise ValueError(
            f"{weapon.name} shoots at the wielder's Strength, but {shooter.name} has none"
        )
    strength = profile.strength.resolve(wielder_strength or 0)
    logger.debug(
        "resolving %d %s (BS %d) shooting %s at %s (T %d), S %d AP %d",
        shooters,
        shooter.name,
        ballistic_skill,
        weapon.name,
        target.name,
        toughness,
        strength,
        profile.armour_piercing,
    )

    armour_value, notes = defender_armour(target, armoury)
    for unit in (shooter, target):
        notes.extend(
            f"special rule not factored: {rule} ({unit.name})" for rule in unit.special_rules
        )
    conditions = _engagement_conditions(profile, context, force_short_range)

    # Weapon rules with compiled effects join the dice walk; the rest are
    # reported, exactly as before. Shooting-phase chapter rules (Firing
    # at Long Range, Moving and Shooting) apply to every volley.
    transforms, unfactored = compile_rules(profile.special_rules, rules, conditions)
    notes.extend(f"weapon rule not factored: {rule} ({weapon.name})" for rule in unfactored)
    phase_rules = sorted(
        r.name for r in rules.values() if r.category == _SHOOTING_PHASE and r.effects
    )
    phase_transforms, phase_unfactored = compile_rules(phase_rules, rules, conditions)
    transforms.extend(phase_transforms)
    notes.extend(f"core rule not factored: {name}" for name in phase_unfactored)
    if weapon.notes is not None:
        notes.append(f"weapon notes not factored ({weapon.name}): {weapon.notes}")

    # Wounds accumulate into whole slain models; a profile with no printed
    # Wounds ("-") is treated as a single-Wound model.
    defender_wounds = target.profiles[0][Characteristic.WOUNDS] or 1

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
