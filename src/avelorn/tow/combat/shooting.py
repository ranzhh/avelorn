"""The shooting attack chain: hit, wound, armour save, ward save.

Works on 1-Wound rank-and-file targets; multi-wound carry-over is not
modelled yet. Anything the math cannot honour (special rules,
unrecognised equipment) is reported in ``ShootingResult.notes`` rather
than silently ignored.
"""

from dataclasses import dataclass

from avelorn.core.dice import binomial_distribution, expected_value, p_d6_at_least
from avelorn.tow.combat.charts import (
    BEST_ARMOUR_VALUE,
    UNARMOURED,
    armour_save_target,
    hit_probability,
    save_probability,
    shooting_hit_target,
    wound_target,
)
from avelorn.tow.combat.weapons import MissileWeapon
from avelorn.tow.schema.unit import Unit

# Equipment whose armour contribution is verified against the rulebook,
# as improvements over the unarmoured value of 7+. Keys use the canonical
# Title Case from the whfb.app importer writes into data/.
_ARMOUR_IMPROVEMENTS = {"Light Armour": 1, "Shield": 1}


@dataclass(frozen=True)
class ShootingResult:
    """Outcome of a volley of shooting attacks against 1-Wound models."""

    shots: int
    hit_target: int
    wound_target: int | None
    save_target: int | None
    ward_target: int | None
    p_hit: float
    p_wound: float
    p_unsaved: float  # per-shot probability of an unsaved wound
    distribution: list[float]  # index k = P(exactly k unsaved wounds)
    notes: tuple[str, ...] = ()

    @property
    def expected_wounds(self) -> float:
        """Mean number of unsaved wounds.

        Returns:
            The expectation of the wound distribution.
        """
        return expected_value(self.distribution)


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
    notes: tuple[str, ...] = (),
) -> ShootingResult:
    """Resolve a volley of identical shooting attacks probabilistically.

    Returns:
        The per-shot probabilities and the distribution of unsaved wounds.
    """
if shots < 0:
    raise ValueError("shots must be >= 0")

hit = shooting_hit_target(ballistic_skill, hit_modifier)
wound = wound_target(strength, toughness)
save = armour_save_target(armour_value, armour_piercing)

    p_hit = hit_probability(hit)
    p_wound = p_d6_at_least(wound) if wound is not None else 0.0
    p_save_fail = 1.0 - save_probability(save)
    p_ward_fail = 1.0 - save_probability(ward_target)
    p_unsaved = p_hit * p_wound * p_save_fail * p_ward_fail

    return ShootingResult(
        shots=shots,
        hit_target=hit,
        wound_target=wound,
        save_target=save,
        ward_target=ward_target,
        p_hit=p_hit,
        p_wound=p_wound,
        p_unsaved=p_unsaved,
        distribution=binomial_distribution(shots, p_unsaved),
        notes=notes,
    )


def shoot_unit(
    attacker: Unit,
    defender: Unit,
    shooters: int,
    weapon: MissileWeapon,
    hit_modifier: int = 0,
) -> ShootingResult:
    """Resolve ``shooters`` models of ``attacker`` shooting ``weapon`` at ``defender``.

    One shot per model, using each unit's first (rank-and-file) profile.
    Special rules and unrecognised equipment are not factored into the
    math; they are listed in the result's notes.

    Returns:
        The shooting outcome.

    Raises:
        ValueError: if the attacker profile has no Ballistic Skill or the
            defender profile has no Toughness.
    """
    # TODO: profile selection is naive. A unit that bought a champion
    # shoots with the champion too (possibly at higher BS, e.g. an
    # archers' Sentinel at BS 5), and units with split profiles need
    # per-profile resolution with the volley combined. Requires a notion
    # of unit composition (which models are actually fielded), which the
    # schema does not have yet.
    ballistic_skill = attacker.profiles[0].ballistic_skill
    toughness = defender.profiles[0].toughness
    if ballistic_skill is None:
        raise ValueError(f"{attacker.name} has no Ballistic Skill; it cannot shoot")
    if toughness is None:
        raise ValueError(f"{defender.name} has no Toughness; it cannot be wounded")

    armour_value, notes = _defender_armour(defender)
    for unit in (attacker, defender):
        notes.extend(
            f"special rule not factored: {rule} ({unit.name})" for rule in unit.special_rules
        )
    notes.extend(
        f"weapon rule not factored: {rule} ({weapon.name})" for rule in weapon.special_rules
    )

    return shoot(
        shots=shooters,
        ballistic_skill=ballistic_skill,
        strength=weapon.strength,
        toughness=toughness,
        armour_value=armour_value,
        armour_piercing=weapon.armour_piercing,
        hit_modifier=hit_modifier,
        notes=tuple(notes),
    )


def _defender_armour(defender: Unit) -> tuple[int | None, list[str]]:
    improvement = 0
    notes: list[str] = []
    for item in defender.equipment:
        bonus = _ARMOUR_IMPROVEMENTS.get(item)
        if bonus is None:
            notes.append(f"equipment not factored: {item} ({defender.name})")
        else:
            improvement += bonus
    value = max(UNARMOURED - improvement, BEST_ARMOUR_VALUE)
    return (value if value < UNARMOURED else None), notes
