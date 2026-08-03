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
from fractions import Fraction
from typing import ClassVar

from avelorn.core.dice import expected_value
from avelorn.core.game import Phase
from avelorn.tow.contingent import Contingent, Loadout
from avelorn.tow.engine.armour import defender_armour
from avelorn.tow.engine.attack import (
    ArmourSave,
    AttackProfile,
    Modifier,
    Outcome,
    Reroll,
    Roll,
    RollToHitShooting,
    RollToWound,
    Transform,
    WardSave,
    resolve_attack,
    roll_target,
)
from avelorn.tow.engine.casualties import wound_and_casualties
from avelorn.tow.engine.characteristic_tests import pass_probability
from avelorn.tow.engine.charts import (
    armour_save_target,
    hit_probability,
    save_probability,
    shooting_hit_target,
    wound_probability,
    wound_target,
)
from avelorn.tow.engine.rules import (
    AttackFacts,
    EffectiveValue,
    GateContext,
    MovementFacts,
    ShootingFacts,
    WeaponFacts,
    compile_rules,
    effective_armour_value,
    effective_rerolls,
    factored_notes,
)
from avelorn.tow.schema.psychology import PanicCause
from avelorn.tow.schema.rule import AttackKind, RerollEffect, Rule
from avelorn.tow.schema.stage import Side, Stage
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
    rerolls: Sequence[Reroll] = (),
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
    bespoke code hooks — the escape hatch for what a record cannot say;
    ``rerolls`` are the re-roll grants the walk applies to the dice they
    cover, whichever side's rules granted them.

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
        rerolls,
    )
    p_unsaved = float(resolution.p_unsaved)
    p_kill = float(resolution.p_of(Outcome.INSTANT_KILL))
    # Report the walk's effective targets (modifiers included) so the printed
    # figures match the math. The To Hit target and the save target both carry
    # their unconditional modifiers — the save's flat Armour Piercing from a
    # unit rule (Arrows of Isha on a bow). A save worsened past 6+ is no save
    # (None), matching the chart convention; a rollless target (no armour)
    # likewise. A conditional bump (Armour Bane, on a natural 6) is not shown,
    # as it applies only on that face.
    if isinstance(resolution.hit_target, int):
        hit = resolution.hit_target
    if isinstance(resolution.save_target, int):
        save = resolution.save_target if resolution.save_target <= 6 else None
    else:
        save = None
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
    shooter: Contingent,
    weapon: Weapon,
    profile: WeaponProfile,
    distance: int | None,
    force_short_range: bool,
) -> GateContext:
    # The gate facts for the shooter's volley: the weapon it fires (its family
    # and name, for Arrows of Isha's "any bow"), the armour it wears, whether the
    # model moved, and whether the shot is at long range (a shot forced short, a
    # Stand & Shoot reaction, never is). The weapon is the one *chosen* for the
    # volley, which need not be the one in hand (an unarmed unit fires its sole
    # missile weapon), so it is passed rather than read off the shooter.
    # ``combat`` is absent (a shooter is not engaged in close combat) and
    # ``target_of`` is absent (the shooter is the attacker, not a target) — the
    # defender's incoming-attack facts are built separately for its armour save.
    return GateContext(
        wielding=WeaponFacts(type=weapon.weapon_type, name=weapon.name),
        worn=shooter.armour_facts,
        # a shooter never charged: charge stays None
        movement=MovementFacts(moved=shooter.movement.moved),
        shooting=ShootingFacts(
            at_long_range=False if force_short_range else _at_long_range(profile, distance)
        ),
    )


def shoot_unit(
    attacker: Contingent,
    defender: Contingent,
    *,
    phase_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
    distance: int | None = None,
    hit_modifier: int = 0,
    force_short_range: bool = False,
    stand_and_shoot: bool = False,
) -> ShootingResult:
    """Resolve ``attacker`` shooting a volley at ``defender``.

    One shot per model in the unit's front rank (``attacker.formation.files``),
    using each side's first (rank-and-file) profile and the missile profile
    of the weapon the attacker shoots with (``attacker.shooting_weapon()`` —
    the weapon armed through
    :meth:`~avelorn.tow.contingent.Contingent.wielding`, or the sole carried
    missile weapon when none is armed); casualties cap at the defender's
    fielded ``models``.
    Only the front rank fires on flat ground; a hill would add a rank
    (not modelled). A weapon with Volley Fire adds half of each rank
    behind the front (rounding up) while the unit is stationary
    (``attacker.movement.moved`` False) and not making a Stand & Shoot reaction.
    To resolve a partial volley (only some models in range
    or sight), field the shooting subset as its own contingent. The weapon's
    rules compile from the loadout's resolved index, and the defender's save
    folds from its loadout. ``phase_rules`` are the phase's rules in force —
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
        ValueError: if the attacker has no missile weapon to shoot with (none
            carried, or several unarmed), the weapon has no missile profile,
            the attacker profile has no Ballistic Skill, the defender profile
            has no Toughness, or the weapon shoots at the wielder's Strength
            and the attacker profile has none.
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
    chosen = attacker.shooting_weapon()
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

    # The defender's own rules may better its save against this volley (Lion
    # Cloak's +1 vs non-magical shooting), gated on the incoming attack: a
    # shooting attack, magical iff the missile weapon is. Parry stays inert here
    # — it gates on being engaged in close combat, and a shot target is not.
    armour_value = defender_armour(defender.loadout.armour)
    incoming = GateContext(
        wielding=defender.weapon_facts,
        worn=defender.armour_facts,
        target_of=AttackFacts(
            kind=AttackKind.SHOOTING,
            magical="Magical Attacks" in profile.special_rules,
        ),
    )
    if armour_value is None:
        defender_armour_value = EffectiveValue(0)
    else:
        defender_armour_value = effective_armour_value(
            armour_value,
            defender.loadout.rules,
            incoming,
        )
        armour_value = defender_armour_value.value
    conditions = _engagement_conditions(attacker, chosen, profile, distance, force_short_range)

    # Weapon rules with compiled effects join the dice walk; the rest are
    # reported, exactly as before. Shooting-phase chapter rules (Firing
    # at Long Range, Moving and Shooting) apply to every volley.
    modifiers, unfactored = compile_rules(
        profile.special_rules, attacker.loadout.weapon_rules, conditions
    )
    if volley_fire:
        unfactored = [rule for rule in unfactored if rule != "Volley Fire"]

    # The attacker's own unit rules may also shape the volley — Arrows of Isha
    # improves a bow's Armour Piercing and grants it Armour Bane (1) — gated on
    # the weapon in hand's family and expanded through the loadout's granted
    # rules. A rule the walk cannot factor (Strike First's Initiative set,
    # Ithilmar Weapons' re-roll) stays unfactored and noted; the factored ones
    # are claimed out of the "special rule not factored" notes below.
    unit_index = {rule.name: rule for rule in attacker.loadout.rules}
    unit_modifiers, unit_unfactored = compile_rules(
        list(unit_index), unit_index, conditions, grants=attacker.loadout.granted_rules
    )
    modifiers.extend(unit_modifiers)

    # The defender's own rules reach the same walk from the target seat: an
    # enemy-subject rule of the defender's ("enemy units shooting at this
    # unit suffer -1 To Hit") lands on this volley's Roll to Hit, gated on
    # the defender's facts — the incoming attack among them. Its
    # armour-value rules stay the armour fold's (claimed there).
    defender_index = {rule.name: rule for rule in defender.loadout.rules}
    defender_modifiers, defender_unfactored = compile_rules(
        list(defender_index),
        defender_index,
        incoming,
        seat=Side.TARGET,
        grants=defender.loadout.granted_rules,
    )
    modifiers.extend(defender_modifiers)
    defender_walk_rules = {name for name in defender_index if name not in defender_unfactored}

    # Each side's re-roll grants, from its own seat: the attacker's
    # enemy-subject grants re-roll the defender's dice (a forced re-roll of
    # successful saves), the defender's own grants its own (a save re-roll
    # while shot at). The attacker's own-dice grants gate on the volley's
    # facts like any weapon rule (a combat-only grant is honoured inert).
    # not yet: the volley profile's weapon-borne grants (a magic bow's own
    # re-roll) are not read here, where _engage reads the profile in use —
    # nothing in the corpus prints one; a magic missile weapon joins by
    # compiling its profile rules into this call, as combat does.
    rerolls = effective_rerolls(attacker.loadout.rules, conditions, seat=Side.ATTACKER)
    defender_rerolls = effective_rerolls(defender.loadout.rules, incoming, seat=Side.TARGET)
    claimed = {name for name in unit_index if name not in unit_unfactored} | {*rerolls.factored}

    notes: list[str] = []
    notes.extend(
        f"special rule not factored: {rule} ({shooter.name})"
        for rule in shooter.special_rules
        if rule not in claimed
    )
    notes.extend(
        factored_notes(
            attacker.loadout.rules, claimed, shooter.name, attacker.loadout.granted_rules
        )
    )
    defender_claimed = {
        *defender_armour_value.factored,
        *defender_rerolls.factored,
        *defender_walk_rules,
    }
    notes.extend(
        f"special rule not factored: {rule} ({target.name})"
        for rule in target.special_rules
        if rule not in defender_claimed
    )
    notes.extend(
        factored_notes(
            defender.loadout.rules, defender_claimed, target.name, defender.loadout.granted_rules
        )
    )
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
        rerolls=(*rerolls.rerolls, *defender_rerolls.rerolls),
        notes=tuple(notes),
    )


@dataclass(frozen=True)
class PanicTest(Roll):
    """The Make Panic Tests step's dice: 2D6 against the unit's Leadership.

    Rolled once for the whole unit — no single natural face exists, so
    it is no attack roll and a ``natural:`` trigger cannot name it. The
    printed bounds (a double 6 always fails, a double 1 always passes)
    live in the characteristic-test procedure this delegates to.
    """

    leadership: int | None
    stage: ClassVar[Stage] = Stage.MAKE_PANIC_TESTS

    def chance(self) -> Fraction:
        """The probability the test passes.

        Returns:
            The exact pass probability, 0 for no Leadership at all.
        """
        return pass_probability(Characteristic.LEADERSHIP, self.leadership)


@dataclass(frozen=True)
class PanicResult:
    """Exact outcome probabilities of the Make Panic Tests step."""

    p_test: float  # lost more than 25% of start-of-phase models (and survived)
    p_holds: float  # never tested, or tested and passed
    p_falls_back: float  # failed with more than half its battle strength left
    p_flees: float  # failed at half its battle strength or less
    p_destroyed: float  # every model lost: no unit remains to test
    reroll_from: str | None = None  # the rule that re-rolls a failed test, if any


def make_panic_tests(
    result: ShootingResult,
    defender: Contingent,
    *,
    battle_strength: int | None = None,
) -> PanicResult:
    """Resolve the panic step for one volley's casualty distribution.

    The defender's resolved loadout carries its rules: a re-roll effect
    on this seam whose cause filter admits heavy casualties (this
    seam's only cause) re-rolls a failed test — once, whatever the
    source, per the printed re-roll rules. ``battle_strength`` is the
    unit's model count at the start of the battle, governing the
    printed Fall Back or Flee split; it defaults to the start-of-phase
    count — a unit yet to take any casualties.

    Returns:
        The exact probabilities of each panic outcome.

    Raises:
        ValueError: the result has no target unit size, the size is
            zero, or ``battle_strength`` is smaller than it.
    """
    size = result.target_models
    if size is None or size == 0:
        raise ValueError("panic needs the target unit's size; resolve with it set on the result")
    battle = battle_strength if battle_strength is not None else size
    if battle < size:
        raise ValueError(f"battle strength ({battle}) cannot be below current size ({size})")

    test = PanicTest(defender.unit.highest(Characteristic.LEADERSHIP))
    p_pass = float(test.chance())
    reroll_from = _reroll_grant(defender.loadout, PanicCause.HEAVY_CASUALTIES)
    if reroll_from is not None:
        # A failed test is taken again: both dice, same natural bounds,
        # never more than once whatever the source.
        p_pass = p_pass + (1.0 - p_pass) * p_pass
    tested = holds = falls_back = flees = destroyed = 0.0
    for killed, mass in enumerate(result.casualties):
        if killed == size:
            destroyed += mass
        elif killed * 4 > size:  # "more than a quarter (25%)"
            tested += mass
            holds += mass * p_pass
            remaining = size - killed
            failed = mass * (1.0 - p_pass)
            if remaining * 2 > battle:  # "more than half (50%) ... still remain"
                falls_back += failed
            else:
                flees += failed
        else:
            holds += mass
    logger.debug(
        "panic: p_test=%.3f holds=%.3f falls back=%.3f flees=%.3f destroyed=%.3f",
        tested,
        holds,
        falls_back,
        flees,
        destroyed,
    )
    return PanicResult(
        p_test=tested,
        p_holds=holds,
        p_falls_back=falls_back,
        p_flees=flees,
        p_destroyed=destroyed,
        reroll_from=reroll_from,
    )


def _reroll_grant(loadout: Loadout, cause: PanicCause) -> str | None:
    # The first of the defender's resolved rules granting a re-roll on
    # this seam for this cause; one grant is all a test can ever use.
    # Unresolved rules have no entries, so they cannot grant.
    for rule in loadout.rules:
        for effect in rule.effects:
            if (
                isinstance(effect, RerollEffect)
                and effect.reroll is Stage.MAKE_PANIC_TESTS
                and (not effect.causes or cause in effect.causes)
            ):
                logger.debug("panic re-roll granted by %s", rule.name)
                return rule.name
    return None


@dataclass(frozen=True)
class ShootingPhase(Phase):
    """The Shooting phase: its printed steps, its actions.

    ``in_play`` are the chapter's rules in force — every volley
    resolves under them.
    """

    in_play: Mapping[str, Rule]

    # The printed shooting sequence: every step knows what it rolls —
    # attack dice with their semantics (this Roll to Hit confirms 7+),
    # then the unit-wide 2D6 panic test. The declaration: drift guards
    # hold the attack factory and the Stage order to it.
    steps: ClassVar[tuple[type[Roll], ...]] = (
        RollToHitShooting,
        RollToWound,
        ArmourSave,
        WardSave,
        PanicTest,
    )

    def volley(
        self,
        attacker: Contingent,
        defender: Contingent,
        *,
        distance: int | None = None,
        hit_modifier: int = 0,
    ) -> ShootingResult:
        """One unit shoots another with the weapon in hand, under the rules in force.

        Returns:
            The shooting outcome.
        """
        return shoot_unit(
            attacker,
            defender,
            phase_rules=self.in_play,
            distance=distance,
            hit_modifier=hit_modifier,
        )

    def make_panic_tests(
        self,
        result: ShootingResult,
        defender: Contingent,
        *,
        battle_strength: int | None = None,
    ) -> PanicResult:
        """The panic step for one volley's casualties.

        Returns:
            The panic outcome distribution.
        """
        return make_panic_tests(result, defender, battle_strength=battle_strength)
