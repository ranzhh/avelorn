"""The shooting attack chain: hit, wound, armour save, ward save.

Works on 1-Wound rank-and-file targets; multi-wound carry-over is not
modelled yet. Anything the math cannot honour (special rules,
unrecognised equipment) is reported in ``ShootingResult.notes`` rather
than silently ignored.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from avelorn.core.dice import (
    binomial_distribution,
    cap_distribution,
    expected_value,
    p_d6_at_least,
)
from avelorn.tow.combat.charts import (
    BEST_ARMOUR_VALUE,
    UNARMOURED,
    armour_save_target,
    hit_probability,
    save_probability,
    shooting_hit_target,
    wound_target,
)
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon


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
    targets: int | None = None,
    notes: tuple[str, ...] = (),
) -> ShootingResult:
    """Resolve a volley of identical shooting attacks probabilistically.

    ``targets`` is the number of 1-Wound models in the target unit. When
    given, the casualty distribution caps at it — a volley cannot remove
    more models than the unit contains. The unsaved-wound ``distribution``
    is unaffected; it never depends on how many models receive the wounds.

    Returns:
        The per-shot probabilities, the distribution of unsaved wounds, and
        the casualty distribution (identical to the former when uncapped).

    Raises:
        ValueError: `shots` is negative, or `targets` is negative.
    """
    if shots < 0:
        raise ValueError("shots must be >= 0")
    if targets is not None and targets < 0:
        raise ValueError("targets must be >= 0")

    hit = shooting_hit_target(ballistic_skill, hit_modifier)
    wound = wound_target(strength, toughness)
    save = armour_save_target(armour_value, armour_piercing)

    p_hit = hit_probability(hit)
    p_wound = p_d6_at_least(wound) if wound is not None else 0.0
    p_save_fail = 1.0 - save_probability(save)
    p_ward_fail = 1.0 - save_probability(ward_target)
    p_unsaved = p_hit * p_wound * p_save_fail * p_ward_fail

    distribution = binomial_distribution(shots, p_unsaved)
    casualties = list(distribution) if targets is None else cap_distribution(distribution, targets)

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


def shoot_unit(
    attacker: Unit,
    defender: Unit,
    shooters: int,
    weapon: Weapon,
    *,
    armoury: Mapping[str, Armour] | None = None,
    hit_modifier: int = 0,
    defenders: int | None = None,
) -> ShootingResult:
    """Resolve ``shooters`` models of ``attacker`` shooting ``weapon`` at ``defender``.

    One shot per model, using each unit's first (rank-and-file) profile
    and the weapon's missile profile. ``armoury`` maps printed equipment
    names to armour items; defender equipment it does not resolve — and
    every special rule — is not factored into the math but listed in the
    result's notes.

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

    armour_value, notes = _defender_armour(defender, armoury or {})
    for unit in (attacker, defender):
        notes.extend(
            f"special rule not factored: {rule} ({unit.name})" for rule in unit.special_rules
        )
    notes.extend(
        f"weapon rule not factored: {rule} ({weapon.name})" for rule in profile.special_rules
    )
    if weapon.notes is not None:
        notes.append(f"weapon notes not factored ({weapon.name}): {weapon.notes}")

    # Capping wounds at the model count is only meaningful for 1-Wound
    # models. For a multi-wound target it would conflate wounds with
    # kills, yielding a figure that is neither — so the cap is withheld
    # (casualties stay equal to the wound distribution) and the note below
    # explains why, rather than reporting a confidently wrong number.
    defender_wounds = defender.profiles[0].wounds
    multi_wound = defender_wounds is not None and defender_wounds > 1
    if multi_wound:
        notes.append(
            f"casualties assume 1 Wound per model; {defender.name} has Wounds "
            f"{defender_wounds} (multi-wound carry-over not modelled, size cap not applied)"
        )
    if defenders is not None and not multi_wound:
        notes.append("panic test at 25% casualties not modelled")

    return shoot(
        shots=shooters,
        ballistic_skill=ballistic_skill,
        strength=strength,
        toughness=toughness,
        armour_value=armour_value,
        armour_piercing=profile.armour_piercing,
        hit_modifier=hit_modifier,
        targets=None if multi_wound else defenders,
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
