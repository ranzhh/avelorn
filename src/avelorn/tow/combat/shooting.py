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
from typing import assert_never

from avelorn.core.dice import expected_value
from avelorn.tow.combat.armour import defender_armour
from avelorn.tow.combat.attack import (
    AttackProfile,
    Modifier,
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
from avelorn.tow.combat.contingent import Contingent
from avelorn.tow.combat.rules import compile_rules
from avelorn.tow.schema.rule import Condition, Rule
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.schema.weapon import Weapon, WeaponProfile

logger = logging.getLogger(__name__)


# An empty registry as the default: every rule stays unfactored, visibly.
# No rules in force: the volley resolves under weapon and armour alone.
_NONE_IN_PLAY: Mapping[str, Rule] = {}


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
    modifiers: Sequence[Modifier] = (),
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

    ``modifiers`` are the compiled records of printed conditional
    modifiers, applied to each attack's dice walk; ``transforms`` are
    bespoke code hooks — the escape hatch for what a record cannot say.

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
        AttackProfile.shooting(
            hit_target=hit,
            wound_target=roll_target(wound),
            save_target=roll_target(save),
            ward_target=roll_target(ward_target),
        ),
        modifiers,
        transforms,
    )
    p_unsaved = float(resolution.p_unsaved)
    p_kill = float(resolution.p_of(Outcome.INSTANT_KILL))
    # Report the walk's effective To Hit target (modifiers included) so
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


def _at_long_range(profile: WeaponProfile, distance: int | None) -> bool | None:
    # Whether the shot is at long range, "further away than half the
    # weapon's maximum range". Needs both a known distance and a numeric
    # weapon range; without them the band is unknown (None).
    if distance is None or not isinstance(profile.range, int):
        return None
    return distance > profile.range / 2


def _engagement_conditions(
    profile: WeaponProfile, moved: bool, distance: int | None, force_short_range: bool
) -> dict[Condition, bool | None]:
    # One fact per Condition member; None = unknown. The match is
    # exhaustive (assert_never), so a new member fails the type check —
    # and a drift-guard test — until it is answered here. A shot forced
    # short (a Stand & Shoot reaction) is never at long range.
    def fact(condition: Condition) -> bool | None:
        match condition:
            case Condition.MOVED:
                return moved
            case Condition.AT_LONG_RANGE:
                return False if force_short_range else _at_long_range(profile, distance)
            case Condition.FIRST_ROUND_OF_COMBAT:
                # A volley is not struck in a round of close combat (a
                # unit in combat cannot shoot), so the fact never arises.
                return False
            case unanswered:
                assert_never(unanswered)

    return {condition: fact(condition) for condition in Condition}


def shoot_unit(
    attacker: Contingent,
    defender: Contingent,
    weapon: Weapon,
    *,
    phase_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
    distance: int | None = None,
    hit_modifier: int = 0,
    force_short_range: bool = False,
    stand_and_shoot: bool = False,
) -> ShootingResult:
    """Resolve ``attacker`` shooting a volley of ``weapon`` at ``defender``.

    One shot per model in the unit's front rank (``attacker.formation.files``),
    using each side's first (rank-and-file) profile and the weapon's
    missile profile; casualties cap at the defender's fielded ``models``.
    Only the front rank fires on flat ground; a hill would add a rank
    (not modelled). A weapon with Volley Fire adds half of each rank
    behind the front (rounding up) while the unit is stationary
    (``attacker.movement.moved`` False) and not making a Stand & Shoot reaction.
    To resolve a partial volley (only some models in range
    or sight), field the shooting subset as its own contingent. ``weapon``
    is the per-action
    choice and must be carried — resolve a text boundary's printed name
    through ``attacker.loadout.weapon(...)``; the weapon's rules compile
    from the loadout's resolved index, and the defender's save folds
    from its loadout. ``phase_rules`` are the phase's rules in force —
    the chapter rules that apply to every volley (Firing at Long Range,
    Moving and Shooting), resolved by printed name; the Game assembles
    the mapping once (game.in_play), the way a loadout resolves a
    unit's names at fielding. Unit special rules are not factored into
    the math yet — every one is listed in the result's notes.

    Whether the shooter moved is the shooter's own state
    (``attacker.movement.moved``). ``distance`` is the range to the target — the
    one relational fact of the shot; a rule conditioned on a range left
    unknown (``distance`` None) stays unfactored and noted. Rules whose
    category is the shooting phase chapter apply to every volley, gated by
    their conditions. ``force_short_range`` treats the
    shot as within half range whatever the distance, so Firing at Long
    Range is honoured as a no-op rather than left unknown and noted — a
    mechanic a Stand & Shoot uses, but not only it. ``stand_and_shoot``
    marks the shot as a Stand & Shoot charge reaction, which forbids
    Volley Fire; it is kept separate from ``force_short_range`` so a
    future ability that forces short range does not disable Volley Fire.

    Returns:
        The shooting outcome.

    Raises:
        ValueError: if the weapon is not carried or has no missile
            profile, the attacker profile has no Ballistic Skill, the
            defender profile has no Toughness, or the weapon shoots at
            the wielder's Strength and
            the attacker profile has none.
    """
    # Only the unit's front rank fires (shooting-with-more-than-one-rank);
    # a unit on a hill fires with one rank more, not modelled — flat ground
    # is assumed. Casualties still cap at the whole target unit's size.
    shooters, defenders = attacker.formation.files, defender.models
    shooter, target = attacker.unit, defender.unit
    # TODO: profile selection is naive. A unit that bought a champion
    # shoots with the champion too (possibly at higher BS, e.g. an
    # archers' Sentinel at BS 5), and units with split profiles need
    # per-profile resolution with the volley combined. Requires a notion
    # of unit composition (which models are actually fielded), which the
    # schema does not have yet.
    chosen = attacker.wields(weapon)
    profile = chosen.missile_profile
    if profile is None:
        raise ValueError(f"{chosen.name} has no missile profile; it cannot shoot")
    ballistic_skill = shooter.profiles[0][Characteristic.BALLISTIC_SKILL]
    toughness = target.profiles[0][Characteristic.TOUGHNESS]
    if ballistic_skill is None:
        raise ValueError(f"{shooter.name} has no Ballistic Skill; it cannot shoot")
    if toughness is None:
        raise ValueError(f"{target.name} has no Toughness; it cannot be wounded")

    wielder_strength = shooter.profiles[0][Characteristic.STRENGTH]
    if profile.strength.is_relative and wielder_strength is None:
        raise ValueError(
            f"{chosen.name} shoots at the wielder's Strength, but {shooter.name} has none"
        )
    strength = profile.strength.resolve(wielder_strength or 0)

    # Volley Fire: half of each rank behind the front (rounding up) also
    # fires, but only while the unit is stationary and never on a Stand &
    # Shoot reaction (special-rules/volley-fire) — its own fact, not the
    # short-range one (a future ability could force short range without
    # being a reaction). It is a rank rule, not a dice modifier, so it
    # lands here on the shot count, not in the walk. The unit's movement
    # is always known, so its use is always settled: it fires, or is
    # honoured with no extra shots, and is claimed out of the notes below.
    volley_fire = "Volley Fire" in profile.special_rules
    if volley_fire and not stand_and_shoot and not attacker.movement.moved:
        shooters += sum((rank + 1) // 2 for rank in attacker.formation.rear_rank_sizes)
    logger.debug(
        "resolving %d %s (BS %d) shooting %s at %s (T %d), S %d AP %d",
        shooters,
        shooter.name,
        ballistic_skill,
        chosen.name,
        target.name,
        toughness,
        strength,
        profile.armour_piercing,
    )

    armour_value = defender_armour(defender.loadout)
    notes: list[str] = []
    for side in (shooter, target):
        notes.extend(
            f"special rule not factored: {rule} ({side.name})" for rule in side.special_rules
        )
    conditions = _engagement_conditions(
        profile, attacker.movement.moved, distance, force_short_range
    )

    # Weapon rules with compiled effects join the dice walk; the rest are
    # reported, exactly as before. Shooting-phase chapter rules (Firing
    # at Long Range, Moving and Shooting) apply to every volley.
    modifiers, unfactored = compile_rules(
        profile.special_rules, attacker.loadout.weapon_rules, conditions
    )
    if volley_fire:
        unfactored = [rule for rule in unfactored if rule != "Volley Fire"]
    notes.extend(f"weapon rule not factored: {rule} ({chosen.name})" for rule in unfactored)
    phase_modifiers, phase_unfactored = compile_rules(sorted(phase_rules), phase_rules, conditions)
    modifiers.extend(phase_modifiers)
    notes.extend(f"core rule not factored: {name}" for name in phase_unfactored)
    if chosen.notes is not None:
        notes.append(f"weapon notes not factored ({chosen.name}): {chosen.notes}")

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
        modifiers=modifiers,
        notes=tuple(notes),
    )
