"""One side striking in close combat: hit, wound, armour save, ward save.

The close-combat analogue of :func:`~avelorn.tow.combat.shooting.shoot`,
for a single striking side: ``attacks`` blows land on a unit of
identical models. The To Hit stage uses the WS-vs-WS chart and close
combat's hit roll (a natural 6 always hits, no 7+ confirmation); every
later stage — To Wound, armour and ward saves, Remove Casualties — is
shared with shooting, since the rulebook resolves them identically
(the-combat-phase/roll-to-wound-combat says the To Wound chart matches,
and determining-armour-saves-combat defers to the Shooting section).

This models one Initiative step of one side. Striking order between the
two sides — and the casualties a higher-Initiative side removes before
the other strikes back — is composed on top of this, later.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from avelorn.core.dice import expected_value
from avelorn.tow.combat.armour import defender_armour
from avelorn.tow.combat.attack import (
    AttackProfile,
    HitRoll,
    Outcome,
    RollState,
    RollTarget,
    Transform,
    resolve_attack,
)
from avelorn.tow.combat.casualties import wound_and_casualties
from avelorn.tow.combat.charts import (
    armour_save_target,
    melee_hit_probability,
    melee_hit_target,
    save_probability,
    wound_probability,
    wound_target,
)
from avelorn.tow.combat.rules import compile_rules
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Characteristic, Unit
from avelorn.tow.schema.weapon import Weapon

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrikeResult:
    """Outcome of one side's attacks against a unit in close combat."""

    attacks: int
    hit_target: int
    wound_target: int | None
    save_target: int | None
    ward_target: int | None
    p_hit: float
    p_wound: float
    p_unsaved: float  # per-attack probability of an unsaved wound
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

        Returns:
            The expectation of the casualty distribution.
        """
        return expected_value(self.casualties)


def strike(
    attacks: int,
    weapon_skill: int,
    target_weapon_skill: int,
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
) -> StrikeResult:
    """Resolve a set of identical close-combat attacks probabilistically.

    ``attacks`` blows are rolled at ``weapon_skill`` against a defender of
    ``target_weapon_skill``; ``hit_modifier`` follows the printed sign
    convention (a penalty is negative and raises the target). Wounds,
    saves and casualty accumulation match shooting: see
    :func:`~avelorn.tow.combat.shooting.shoot` for ``wounds_per_model``,
    ``targets`` and ``transforms``.

    Returns:
        The per-attack probabilities, the distribution of unsaved wounds,
        and the casualty (models-removed) distribution.

    Raises:
        ValueError: `attacks` is negative, `targets` is negative, or
            `wounds_per_model` is less than 1.
    """
    if attacks < 0:
        raise ValueError("attacks must be >= 0")
    if targets is not None and targets < 0:
        raise ValueError("targets must be >= 0")
    if wounds_per_model < 1:
        raise ValueError("wounds_per_model must be >= 1")

    hit = melee_hit_target(weapon_skill, target_weapon_skill) - hit_modifier
    wound = wound_target(strength, toughness)
    save = armour_save_target(armour_value, armour_piercing)

    resolution = resolve_attack(
        AttackProfile(
            hit_target=hit,
            wound_target=_roll_target(wound),
            save_target=_roll_target(save),
            ward_target=_roll_target(ward_target),
        ),
        transforms,
        hit_roll=HitRoll.MELEE,
    )
    p_unsaved = float(resolution.p_unsaved)
    p_kill = float(resolution.p_of(Outcome.INSTANT_KILL))
    # Report the walk's effective To Hit target (transforms included).
    if isinstance(resolution.hit_target, int):
        hit = resolution.hit_target
    p_hit = melee_hit_probability(hit)
    p_wound = wound_probability(wound)
    logger.debug(
        "per-attack: p=%.3f = hit %.3f x wound %.3f x save-fail %.3f x ward-fail %.3f",
        p_unsaved,
        p_hit,
        p_wound,
        1.0 - save_probability(save),
        1.0 - save_probability(ward_target),
    )

    distribution, casualties = wound_and_casualties(
        attacks,
        p_unsaved=p_unsaved,
        p_kill=p_kill,
        wounds_per_model=wounds_per_model,
        targets=targets,
    )

    return StrikeResult(
        attacks=attacks,
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


def strike_unit(
    attacker: Unit,
    defender: Unit,
    fighters: int,
    weapon: Weapon,
    *,
    armoury: Mapping[str, Armour] | None = None,
    rules: Mapping[str, Rule] | None = None,
    hit_modifier: int = 0,
    defenders: int | None = None,
) -> StrikeResult:
    """Resolve ``fighters`` models of ``attacker`` fighting ``weapon`` against ``defender``.

    Each fighter makes its full Attacks with the weapon's Combat profile,
    using each unit's first (rank-and-file) profile. ``armoury`` maps
    printed equipment names to armour items; ``rules`` maps printed rule
    names to rule entries, whose effects compile into the dice walk.
    Anything either mapping does not resolve — and every unit special
    rule — is not factored into the math but listed in the result's notes.

    ``defenders`` is the number of models fielded in the target unit; when
    given, casualties cap at it.

    Returns:
        The close-combat outcome for this side's blows.

    Raises:
        ValueError: the weapon has no Combat profile, either profile lacks
            Weapon Skill, the attacker profile has no Attacks, the defender
            profile has no Toughness, or the weapon strikes at the
            wielder's Strength and the attacker profile has none.
    """
    # TODO(#46): rank-and-file profile only. A champion fighting at a
    # different WS is a separate attack batch that must be composed, which
    # needs a notion of unit composition. Supporting attacks and the
    # fighting rank are #28 (formations): every fighter here is treated as
    # in base contact making its full Attacks.
    profile = weapon.combat_profile
    if profile is None:
        raise ValueError(f"{weapon.name} has no Combat profile; it cannot fight")
    weapon_skill = attacker.profiles[0][Characteristic.WEAPON_SKILL]
    target_weapon_skill = defender.profiles[0][Characteristic.WEAPON_SKILL]
    attacks_per_model = attacker.profiles[0][Characteristic.ATTACKS]
    toughness = defender.profiles[0][Characteristic.TOUGHNESS]
    if weapon_skill is None:
        raise ValueError(f"{attacker.name} has no Weapon Skill; it cannot fight")
    if target_weapon_skill is None:
        raise ValueError(f"{defender.name} has no Weapon Skill; its To Hit is undefined")
    if attacks_per_model is None:
        raise ValueError(f"{attacker.name} has no Attacks; it cannot fight")
    if toughness is None:
        raise ValueError(f"{defender.name} has no Toughness; it cannot be wounded")

    wielder_strength = attacker.profiles[0][Characteristic.STRENGTH]
    if profile.strength.is_relative and wielder_strength is None:
        raise ValueError(
            f"{weapon.name} strikes at the wielder's Strength, but {attacker.name} has none"
        )
    strength = profile.strength.resolve(wielder_strength or 0)
    attacks = fighters * attacks_per_model
    logger.debug(
        "resolving %d %s (WS %d, A %d) vs %s (WS %d, T %d), S %d AP %d",
        fighters,
        attacker.name,
        weapon_skill,
        attacks_per_model,
        defender.name,
        target_weapon_skill,
        toughness,
        strength,
        profile.armour_piercing,
    )

    armour_value, notes = defender_armour(defender, armoury or {})
    for unit in (attacker, defender):
        notes.extend(
            f"special rule not factored: {rule} ({unit.name})" for rule in unit.special_rules
        )
    # Melee engagement conditions (charging, flank/rear, ...) are not
    # modelled yet, so no facts are supplied: a rule needing one stays
    # unfactored and noted.
    transforms, unfactored = compile_rules(profile.special_rules, rules or {})
    notes.extend(f"weapon rule not factored: {rule} ({weapon.name})" for rule in unfactored)
    if weapon.notes is not None:
        notes.append(f"weapon notes not factored ({weapon.name}): {weapon.notes}")

    # Wounds accumulate into whole slain models; a profile with no printed
    # Wounds ("-") is treated as a single-Wound model.
    defender_wounds = defender.profiles[0][Characteristic.WOUNDS] or 1

    return strike(
        attacks,
        weapon_skill=weapon_skill,
        target_weapon_skill=target_weapon_skill,
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
