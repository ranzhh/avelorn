"""One side striking in close combat: hit, wound, armour save, ward save.

The close-combat analogue of :func:`~avelorn.tow.phases.shooting.shoot`,
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
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from fractions import Fraction
from itertools import product
from math import isclose
from typing import ClassVar, NamedTuple, overload

from avelorn.core.dice import expected_value
from avelorn.core.distribution import Distribution, Probability
from avelorn.core.game import Phase
from avelorn.tow.contingent import Contingent
from avelorn.tow.engine.attack import (
    ArmourSave,
    AttackProfile,
    Modifier,
    Outcome,
    Reroll,
    Roll,
    RollState,
    RollToHitCombat,
    RollToWound,
    Transform,
    WardSave,
    resolve_attack,
    roll_target,
)
from avelorn.tow.engine.casualties import (
    AttackBatch,
    batched_wound_and_casualties,
    wound_and_casualties,
)
from avelorn.tow.engine.charts import (
    armour_save_target,
    melee_hit_probability,
    melee_hit_target,
    save_probability,
    wound_probability,
    wound_target,
)
from avelorn.tow.engine.rules import (
    ArmourFacts,
    AttackFacts,
    ChargeEvent,
    CombatFacts,
    EffectiveHits,
    EffectiveValue,
    FoeFacts,
    GateContext,
    MovementFacts,
    ShootingFacts,
    WeaponFacts,
    attack_marks,
    barred_worn,
    compile_rules,
    effective_automatic_hits,
    effective_characteristic,
    effective_combat_result_bonus,
    factored_notes,
    forced_outcome,
    outcome_substitutions,
)
from avelorn.tow.engine.seats import Defence, Offence
from avelorn.tow.phases.movement import Engagement
from avelorn.tow.schema.psychology import BreakOutcome
from avelorn.tow.schema.rule import AttackKind, Decision, HitOrder, Rule
from avelorn.tow.schema.unit import Characteristic, Profile, ProfileRole
from avelorn.tow.schema.weapon import Weapon

logger = logging.getLogger(__name__)

# No rules in force: the fight resolves under weapon and armour alone.
# The empty mapping is the honest default — a combat that names no chapter
# rules factors none, exactly as a volley does (shooting's _NONE_IN_PLAY).
_NONE_IN_PLAY: Mapping[str, Rule] = {}


@dataclass(frozen=True)
class StrikeResult:
    """Outcome of one side's attacks against a unit in close combat."""

    attacks: int
    hit_target: int
    wound_target: int | None
    save_target: int | None
    ward_target: int | None
    p_hit: Probability
    p_wound: Probability
    p_unsaved: Probability  # per-attack probability of an unsaved wound
    distribution: list[Probability]  # index k = P(exactly k unsaved wounds)
    casualties: list[Probability]  # index k = P(exactly k models removed)
    notes: tuple[str, ...] = ()
    target_models: int | None = None  # size of the target unit, if bounded

    @property
    def expected_wounds(self) -> Probability:
        """Mean number of unsaved wounds.

        Returns:
            The expectation of the wound distribution.
        """
        return expected_value(self.distribution)

    @property
    def expected_casualties(self) -> Probability:
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
    modifiers: Sequence[Modifier] = (),
    transforms: Sequence[Transform] = (),
    notes: tuple[str, ...] = (),
) -> StrikeResult:
    """Resolve a set of identical close-combat attacks probabilistically.

    ``attacks`` blows are rolled at ``weapon_skill`` against a target of
    ``target_weapon_skill``; ``hit_modifier`` follows the printed sign
    convention (a penalty is negative and raises the target). Wounds,
    saves and casualty accumulation match shooting: see
    :func:`~avelorn.tow.phases.shooting.shoot` for ``wounds_per_model``,
    ``targets``, ``modifiers`` and ``transforms``.

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

    hit = melee_hit_target(weapon_skill, target_weapon_skill, hit_modifier)
    wound = wound_target(strength, toughness)
    save = armour_save_target(armour_value, armour_piercing)
    p_unsaved, p_kill, hit = _per_attack(hit, wound, save, ward_target, modifiers, transforms)
    p_hit = melee_hit_probability(hit)
    p_wound = wound_probability(wound)
    logger.debug(
        "per-attack: p=%.3f = hit %.3f x wound %.3f x save-fail %.3f x ward-fail %.3f",
        p_unsaved,
        p_hit,
        p_wound,
        1 - save_probability(save),
        1 - save_probability(ward_target),
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


def _per_attack(
    hit: int,
    wound: int | None,
    save: int | None,
    ward: int | None,
    modifiers: Sequence[Modifier],
    transforms: Sequence[Transform] = (),
    rerolls: Sequence[Reroll] = (),
) -> tuple[Probability, Probability, int]:
    # Walk one melee attack's dice exactly, returning its per-attack
    # unsaved-wound and instant-kill probabilities and the effective To Hit
    # target after the rules' changes — the counts that depend only on the matchup,
    # not on how many models are swinging.
    resolution = resolve_attack(
        AttackProfile.melee(
            hit_target=hit,
            wound_target=roll_target(wound),
            save_target=roll_target(save),
            ward_target=roll_target(ward),
        ),
        modifiers,
        transforms,
        rerolls,
    )
    effective = resolution.hit_target if isinstance(resolution.hit_target, int) else hit
    # Exact, not converted: the walk resolves in Fractions and the aggregations
    # now carry whatever they are handed, so the round is exact end to end.
    return resolution.p_unsaved, resolution.p_of(Outcome.INSTANT_KILL), effective


@dataclass(frozen=True)
class _Engagement:
    """One batch's per-attack resolution against a specific foe.

    The matchup-dependent, fighter-count-independent half of a melee
    strike: the per-attack probabilities and reported targets, the
    ``striker`` throwing the blows, and the target's Wounds. The dice
    walk depends only on the matchup, so it runs once; :meth:`attacks` then
    turns any surviving strength into that many blows (its fighting rank)
    and :func:`wound_and_casualties` into a casualty distribution — the same
    walk serves a return strike whose numbers depend on casualties already
    taken.

    A side contributes one batch per element of its model: the riders (the
    main one), and — for a ridden unit — the mounts, whose batch reads its
    blows off the mount row (``as_mount``). Every batch of a side thins with
    the same casualties, since a slain model takes rider and mount together.
    """

    striker: Contingent
    as_mount: bool
    weapon_skill: EffectiveValue
    # The walk's two seats, resolved once each: the striker's compiled
    # weapon and unit rules, and the target's armour, ward, re-rolls and
    # enemy-subject maluses. What each seat factored is claimed by the
    # callers so a rule in the math is never also reported as not factored;
    # a caller resolving both walks of a round claims both seats' names, a
    # one-sided one reports the seat its walk did not consume.
    offence: Offence
    defence: Defence
    # The weapon the batch swings, and the weapon-rule names other seams of
    # this walk claimed (the attack count, the Initiative read, the re-roll
    # fold). Weapon-rule notes are the caller's to emit — only a full round
    # knows whether the *bearer's own defence* consumed one (Requires Two
    # Hands is resolved while the bearer is the other walk's target), where a
    # one-sided strike honestly leaves it noted (_weapon_rule_notes).
    weapon_name: str
    weapon_claimed: frozenset[str]
    p_unsaved: Probability
    p_kill: Probability
    target_wounds: int
    hit_target: int
    wound_target: int | None
    save_target: int | None
    ward_target: int | None
    p_hit: Probability
    p_wound: Probability
    notes: tuple[str, ...]

    def attacks(self, survivors: int) -> int:
        """The blows ``survivors`` of the striking models throw this round.

        The striker reduced to its ``survivors`` throws its fighting rank
        (:meth:`~avelorn.tow.contingent.Contingent.melee_attacks`) — its full
        frontage until losses cut past the rear ranks into the front one, and
        the narrowed front thereafter — so a body thinned to fewer than a rank
        swings back with fewer attacks. A mount batch reads the mount row's
        Attacks instead, with no supporting term
        (:meth:`~avelorn.tow.contingent.Contingent.mount_attacks`).

        Returns:
            The number of attacks thrown.
        """
        thinned = self.striker.remove_casualties(self.striker.models - survivors)
        return thinned.mount_attacks() if self.as_mount else thinned.melee_attacks()

    def attack_counts(self, survivors: int) -> Distribution[int]:
        """The blows as a distribution — certain here, dice-driven for an automatic batch.

        The shape the Initiative walk consumes (see
        :class:`_AutomaticEngagement`, whose counts genuinely vary).

        Returns:
            The certainty of :meth:`attacks`.
        """
        return Distribution.pure(self.attacks(survivors))


def _engage(
    striker: Contingent,
    target: Contingent,
    *,
    hit_modifier: int,
    conditions: "GateContext | None" = None,
    target_conditions: "GateContext | None" = None,
    phase_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
    element: Profile | None = None,
    weapon: Weapon | None = None,
) -> _Engagement:
    # The matchup half of a strike, shared by strike_unit and fight:
    # extract the striking element's stats, resolve the weapon's Combat
    # profile and the target's armour, compile the weapon's rules, and walk
    # one attack. By default the element is the rank and file (unit.main)
    # swinging the weapon in hand; a mount batch passes its own row and
    # weapon. TODO(#46): a champion fighting at a different WS is a further
    # batch needing unit composition.
    weapon = weapon if weapon is not None else striker.in_hand()
    profile = weapon.combat_profile
    if profile is None:
        raise ValueError(f"{weapon.name} has no Combat profile; it cannot fight")
    striker_unit, target_unit = striker.unit, target.unit
    row = element if element is not None else striker_unit.main
    who = striker_unit.name if element is None else f"{striker_unit.name}'s {row.name}"
    weapon_skill = row[Characteristic.WEAPON_SKILL]
    # Enemy rolls To Hit are made against the rider's Weapon Skill
    # (troop-types-in-detail/split-profile-cavalry), so the target side is
    # always its main row.
    target_weapon_skill = target_unit.main[Characteristic.WEAPON_SKILL]
    attacks_per_model = row[Characteristic.ATTACKS]
    toughness = target_unit.main[Characteristic.TOUGHNESS]
    if weapon_skill is None:
        raise ValueError(f"{who} has no Weapon Skill; it cannot fight")
    if target_weapon_skill is None:
        raise ValueError(f"{target_unit.name} has no Weapon Skill; its To Hit is undefined")
    if attacks_per_model is None:
        raise ValueError(f"{who} has no Attacks; it cannot fight")
    if toughness is None:
        raise ValueError(f"{target_unit.name} has no Toughness; it cannot be wounded")

    wielder_strength = row[Characteristic.STRENGTH]
    if profile.strength.is_relative and wielder_strength is None:
        raise ValueError(f"{weapon.name} strikes at the wielder's Strength, but {who} has none")
    strength = profile.strength.resolve(wielder_strength or 0)

    # The walk's two seats, resolved once each (engine/seats): the striker's
    # weapon and unit rules compiled under its own conditions, and the
    # target's armour, ward, re-rolls and enemy-subject maluses folded under
    # its — the same two resolutions a volley makes.
    offence = Offence.resolve(
        profile,
        weapon_rules=striker.loadout.weapon_rules,
        rules=striker.loadout.rules,
        grants=striker.loadout.granted_rules,
        conditions=conditions,
    )
    defence = Defence.resolve(
        armour=target.loadout.armour,
        rules=target.loadout.rules,
        grants=target.loadout.granted_rules,
        incoming=target_conditions,
        weapon_rules_in_use=target.in_hand_rules(),
    )
    notes: list[str] = []
    modifiers = [*offence.modifiers, *defence.modifiers]
    # A weapon rule the walk cannot factor may still be consumed by another
    # seam: the supporting-rank query (Fight in Extra Rank, folded into the
    # attack count), the striking-order Initiative read (a great weapon's
    # Strike Last, which sets Initiative), or the re-roll seam (Daith's
    # Reaper). Claim all three out of the walk's unfactored notes, the way
    # shooting claims Volley Fire off a volley. The weapon in hand is only
    # ever compiled from its wielder's seat — no second compile covers a
    # weapon rule aimed at the other one — so an inapplicable weapon rule is
    # reported here, not claimed.
    weapon_claimed = frozenset(
        {
            *striker.supporting_ranks().factored,
            *effective_initiative(striker, conditions=conditions).factored,
            *offence.weapon_rerolls.factored,
        }
    )
    phase_compiled = compile_rules(sorted(phase_rules), phase_rules, conditions)
    modifiers.extend(phase_compiled.modifiers)
    notes.extend(
        f"core rule not factored: {name}"
        for name in (*phase_compiled.unfactored, *phase_compiled.inapplicable)
    )
    if weapon.notes is not None:
        notes.append(f"weapon notes not factored ({weapon.name}): {weapon.notes}")

    # Each side's Weapon Skill is read effective, not raw: a rule that
    # modifies it (Martial Prowess's +1 in the first round) shapes both the
    # striker's To Hit and, as the target's WS, the roll against it — each
    # gated on that side's own engagement conditions. A mount's is read
    # printed: the corpus's characteristic modifiers are the rider's own
    # (Elven Reflexes says "(but not its mount)"), and no schema word says
    # which element a modifier reaches yet.
    striker_ws = (
        effective_weapon_skill(striker, conditions)
        if element is None
        else EffectiveValue(weapon_skill)
    )
    target_ws = effective_weapon_skill(target, target_conditions)
    hit = melee_hit_target(striker_ws.value, target_ws.value, hit_modifier)
    wound = wound_target(strength, toughness)
    save = armour_save_target(defence.armour_value, profile.armour_piercing)
    p_unsaved, p_kill, hit = _per_attack(
        hit,
        wound,
        save,
        defence.ward.target,
        modifiers,
        transforms=offence.transforms,
        rerolls=(
            *offence.rerolls.rerolls,
            *offence.weapon_rerolls.rerolls,
            *defence.rerolls.rerolls,
        ),
    )
    # Wounds accumulate into whole slain models; a profile with no printed
    # Wounds ("-") is treated as a single-Wound model. A ridden model's Wounds
    # are the rider's (the-combat-phase/split-profile-cavalry: the rider at
    # zero Wounds removes the whole model), which main already is.
    target_wounds = target_unit.main[Characteristic.WOUNDS] or 1
    logger.debug(
        "%s (WS %d, A %d) vs %s (WS %d, T %d): per-attack unsaved p=%.3f",
        who,
        striker_ws.value,
        attacks_per_model,
        target_unit.name,
        target_ws.value,
        toughness,
        p_unsaved,
    )
    return _Engagement(
        striker=striker,
        as_mount=element is not None and element.role is ProfileRole.MOUNT,
        weapon_skill=striker_ws,
        offence=offence,
        defence=defence,
        weapon_name=weapon.name,
        weapon_claimed=weapon_claimed,
        p_unsaved=p_unsaved,
        p_kill=p_kill,
        target_wounds=target_wounds,
        hit_target=hit,
        wound_target=wound,
        save_target=save,
        ward_target=defence.ward.target,
        p_hit=melee_hit_probability(hit),
        p_wound=wound_probability(wound),
        notes=tuple(notes),
    )


def _mount_engage(
    striker: Contingent,
    target: Contingent,
    *,
    hit_modifier: int = 0,
    conditions: "GateContext | None" = None,
    target_conditions: "GateContext | None" = None,
    phase_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
) -> _Engagement | None:
    # The mount batch of a ridden striker: the mount row fighting with its own
    # Weapon Skill, Strength and Attacks (troop-types-in-detail/
    # split-profile-cavalry), swinging its hooves — "even a cavalry mount is
    # considered to be armed with a hand weapon" (weapons-of-war/hand-weapon).
    # The striker's rules compile into this walk too — a split profile shares
    # its special rules across both elements — gated on the mount's own weapon
    # in hand, so a hand-weapon-gated rule (Ithilmar Weapons) reaches the
    # hooves as printed.
    mount = striker.unit.mount
    if mount is None:
        return None
    hooves = striker.loadout.weapon("Hand Weapon")
    mount_conditions = replace(
        _as_conditions(conditions),
        wielding=WeaponFacts(type=hooves.weapon_type, name=hooves.name),
    )
    return _engage(
        striker,
        target,
        hit_modifier=hit_modifier,
        conditions=mount_conditions,
        target_conditions=target_conditions,
        phase_rules=phase_rules,
        element=mount,
        weapon=hooves,
    )


def _as_conditions(conditions: "GateContext | None") -> GateContext:
    # A context to derive the mount's from; None (all facts unknown) stands in
    # as the empty context, exactly as the evaluator reads it.
    return conditions if conditions is not None else GateContext()


@dataclass(frozen=True)
class _AutomaticEngagement:
    """One side's batch of automatic hits, landing outside the Initiative-ordered blows.

    The Stomp Attacks / Impact Hits batch: every front-rank model — the
    engine's "in base contact", as everywhere — causes ``per_model`` hits
    that skip the Roll to Hit and wound at the model's unmodified Strength
    against the foe's resolved defence. The walk consumes it through the
    same shape as an :class:`_Engagement` (:meth:`attack_counts`,
    ``p_unsaved`` / ``p_kill`` / ``target_wounds``); what differs is that
    the count is genuinely a distribution, dice-driven where a printed
    Attacks value is certain.
    """

    striker: Contingent
    per_model: Distribution[int]
    p_unsaved: Probability
    p_kill: Probability
    target_wounds: int

    def attack_counts(self, survivors: int) -> Distribution[int]:
        """The hits ``survivors`` of the striking models cause.

        The front rank of the thinned body stomps — each model's counts
        summing as independent dice, so two chariots' D6s convolve rather
        than double one die.

        Returns:
            The exact hit-count distribution.
        """
        thinned = self.striker.remove_casualties(self.striker.models - survivors)
        models = thinned.formation.front_ranks(1)
        counts: Distribution[int] = Distribution.pure(0)
        for _ in range(models):
            counts = counts + self.per_model
        return counts


def _automatic_engage(
    striker: Contingent,
    target: Contingent,
    order: HitOrder,
    *,
    conditions: "GateContext | None" = None,
    target_conditions: "GateContext | None" = None,
) -> "tuple[_AutomaticEngagement | None, EffectiveHits]":
    # The automatic-hits batch a side's rules land at ``order`` (Impact Hits
    # ahead of every Initiative step, Stomp Attacks after them all), or None
    # when no hits hold. The hits skip the Roll to Hit and wound at the
    # model's unmodified Strength — the printed characteristic, no weapon
    # profile and no modifier — with no Armour Piercing (the rules print
    # none); the target's resolved defence (armour improved by its own
    # rules, ward, save re-rolls, enemy-subject maluses) stands as for any
    # attack it suffers. The fold comes back whole so the caller claims its
    # factored names and reports its unfactored ones.
    fold = effective_automatic_hits(striker.loadout.rules, order, conditions)
    if all(count == 0 for count in fold.per_model.mass):
        return None, fold
    strength = striker.unit.main[Characteristic.STRENGTH]
    toughness = target.unit.main[Characteristic.TOUGHNESS]
    if strength is None:
        raise ValueError(f"{striker.unit.name} has no Strength; its automatic hits cannot wound")
    if toughness is None:
        raise ValueError(f"{target.unit.name} has no Toughness; it cannot be wounded")
    # "The model making them" — but a datasheet's rules are unit-wide
    # (Unit.special_rules), so a split profile cannot say which row makes
    # the hits. Where the rows agree the ambiguity is harmless; where the
    # mount's Strength differs, refuse loudly rather than resolve at the
    # rank and file's row.
    mount = striker.unit.mount
    if mount is not None and mount[Characteristic.STRENGTH] != strength:
        raise ValueError(
            f"{striker.unit.name}: automatic hits use the Strength of the model making "
            f"them, but datasheet rules are unit-wide and the mount row's Strength "
            f"({mount[Characteristic.STRENGTH]}) differs from the rank and file's "
            f"({strength}); the hits cannot be attributed to a row"
        )
    # The batch carries no weapon — no profile, no modifier — so what the
    # hits *are* is the unit rules' say alone: a magical sword in the
    # striker's hand does not make its stomps magical, while a datasheet
    # printing Magical Attacks marks every attack it makes, these included.
    marks = attack_marks([], {}, striker.loadout.rules)
    incoming = (
        replace(
            target_conditions,
            target_of=AttackFacts(
                kind=AttackKind.CLOSE_COMBAT,
                magical=marks.magical,
                flaming=marks.flaming,
            ),
        )
        if target_conditions is not None
        else None
    )
    defence = Defence.resolve(
        armour=target.loadout.armour,
        rules=target.loadout.rules,
        grants=target.loadout.granted_rules,
        incoming=incoming,
        weapon_rules_in_use=target.in_hand_rules(),
    )
    resolution = resolve_attack(
        AttackProfile.melee(
            hit_target=RollState.AUTOMATIC,
            wound_target=roll_target(wound_target(strength, toughness)),
            save_target=roll_target(armour_save_target(defence.armour_value, 0)),
            ward_target=roll_target(defence.ward.target),
        ),
        defence.modifiers,
        rerolls=defence.rerolls.rerolls,
    )
    return (
        _AutomaticEngagement(
            striker=striker,
            per_model=fold.per_model,
            p_unsaved=resolution.p_unsaved,
            p_kill=resolution.p_of(Outcome.INSTANT_KILL),
            target_wounds=target.unit.main[Characteristic.WOUNDS] or 1,
        ),
        fold,
    )


def strike_unit(
    striker: Contingent,
    target: Contingent,
    *,
    hit_modifier: int = 0,
) -> StrikeResult:
    """Resolve ``striker`` striking against ``target`` with the weapon in hand.

    Only the striker's fighting rank fights — its front rank, in base
    contact, each model making its full Attacks (``striker.melee_attacks``
    — the-combat-phase/who-can-fight): a body deeper than one rank no longer
    throws every model's Attacks, only its front. The Combat profile is the
    weapon the striker is wielding (``striker.in_hand()``), using each
    side's rank-and-file profile (``unit.main``); a ridden striker's mounts
    throw a second batch at the mount row's own line, convolved in before
    the fold to models. Casualties cap at the target's
    fielded ``models``. The target's save folds from its resolved loadout,
    and the weapon's rules compile into the dice walk from the striker's
    resolved loadout (``striker.loadout.weapon_rules``). Unit special rules
    are not factored into the math yet — every one is listed in the result's
    notes. The whole front rank is taken to be in base contact (an equally
    wide foe); a foe of a different frontage, and the supporting attacks the
    rank behind gets from Fight in Extra Rank / Martial Prowess, are not
    modelled yet.

    Returns:
        The close-combat outcome for this side's blows.

    Raises:
        ValueError: the striker has no weapon in hand, the weapon has no
            Combat profile, either profile lacks Weapon Skill, the striker
            profile has no Attacks, the target profile has no Toughness, or
            the weapon strikes at the wielder's Strength and the striker
            profile has none.
    """
    fighters, targets = striker.models, target.models
    if fighters < 0:
        raise ValueError("fighters must be >= 0")
    # A single strike is close combat, so combat is present — but the round it
    # falls in, and how the sides outnumber, are not known here, so first-round
    # and outnumbering rules stay unfactored and noted. The target is the target
    # of this close-combat attack (magical if the striker's weapon in hand is),
    # the fact Parry (combat present) and Lion Cloak (an incoming attack) read
    # for its save; the striker throws the only blows, so it is not itself a
    # target here. Each side carries its own equipment in use, so Parry reads the
    # target's shield and Ithilmar Weapons the striker's hand weapon.
    in_hand = striker.in_hand().combat_profile
    # What the striker's blows *are* (magical, Flaming) is its rules' say —
    # the profile in use's and the unit's own (attack_marks); the same read
    # the striker's seat makes for claiming, so the fact and the note agree.
    marks = attack_marks(
        in_hand.special_rules if in_hand is not None else [],
        striker.loadout.weapon_rules,
        striker.loadout.rules,
    )
    striker_conditions = GateContext(
        combat=CombatFacts(),
        wielding=striker.weapon_facts,
        worn=_worn_in_combat(striker),
        foe=FoeFacts(troop_type=target.unit.troop_type),
    )
    target_conditions = GateContext(
        combat=CombatFacts(),
        wielding=target.weapon_facts,
        worn=_worn_in_combat(target),
        foe=FoeFacts(troop_type=striker.unit.troop_type),
        target_of=AttackFacts(
            kind=AttackKind.CLOSE_COMBAT,
            magical=marks.magical,
            flaming=marks.flaming,
        ),
    )
    engagement = _engage(
        striker,
        target,
        hit_modifier=hit_modifier,
        conditions=striker_conditions,
        target_conditions=target_conditions,
    )
    # A ridden striker throws its mounts' blows too, a second batch at the
    # mount's own line; a one-sided strike asks only what the target suffers,
    # so both batches resolve at full strength and their wounds convolve
    # before the fold to models and the size cap. The reported per-attack
    # figures stay the rank and file's; the mount batch names its own in a
    # note.
    mount_engagement = _mount_engage(
        striker,
        target,
        hit_modifier=hit_modifier,
        conditions=striker_conditions,
        target_conditions=target_conditions,
    )
    engagements = [engagement, *([mount_engagement] if mount_engagement is not None else [])]
    batches = [
        AttackBatch(e.attacks(fighters), p_unsaved=e.p_unsaved, p_kill=e.p_kill)
        for e in engagements
    ]
    attacks = sum(batch.attacks for batch in batches)
    distribution, casualties = batched_wound_and_casualties(
        batches,
        wounds_per_model=engagement.target_wounds,
        targets=targets,
    )
    mount_notes = ()
    if mount_engagement is not None:
        mount = striker.unit.mount
        assert mount is not None  # _mount_engage returned a batch, so the row exists
        mount_notes = (
            f"mount batch folded in: {batches[1].attacks} {mount.name} attacks, "
            f"hitting on {mount_engagement.hit_target}+",
        )
    return StrikeResult(
        attacks=attacks,
        hit_target=engagement.hit_target,
        wound_target=engagement.wound_target,
        save_target=engagement.save_target,
        ward_target=engagement.ward_target,
        p_hit=engagement.p_hit,
        p_wound=engagement.p_wound,
        p_unsaved=engagement.p_unsaved,
        distribution=distribution,
        casualties=casualties,
        notes=(
            # Only the striker throws blows here, so only its fighting-rank
            # rules (Press of Battle) and its effective-WS rules are in the math
            # and claimed; the target's stay noted until it strikes in its turn.
            # The round is unknown here, so a first-round rule like Martial
            # Prowess factors nothing and stays noted. One walk is resolved, so
            # only what it factored is claimed: a rule belonging to the other
            # seat of it (the striker's own save re-roll — nothing saves against
            # it here) is inapplicable, and stays noted rather than passing for
            # factored.
            *_unit_rule_notes(
                striker,
                claimed={
                    *striker.fighting_ranks().factored,
                    *striker.effective_attacks().factored,
                    *(name for e in engagements for name in e.weapon_skill.factored),
                    *(name for e in engagements for name in e.offence.rerolls.factored),
                    *(name for e in engagements for name in e.offence.factored),
                },
            ),
            # The target throws no blows here, but its save is resolved and its
            # rules read from its seat of the walk, so its save-improving rules
            # (Parry), its own re-rolls, and its enemy-subject maluses are all
            # factored and claimed. What only the blows it would throw back
            # could use (Ithilmar Weapons' To Hit re-roll) is the other seat's,
            # and stays noted — it strikes in its own turn.
            *_unit_rule_notes(
                target,
                claimed={
                    *(name for e in engagements for name in e.defence.armour.factored),
                    *(name for e in engagements for name in e.defence.ward.factored),
                    *(name for e in engagements for name in e.defence.rerolls.factored),
                    *(name for e in engagements for name in e.defence.factored),
                },
            ),
            *dict.fromkeys(
                note for e in engagements for note in (*_weapon_rule_notes(e), *e.notes)
            ),
            *mount_notes,
        ),
        target_models=targets,
    )


@dataclass(frozen=True)
class FightResult:
    """Outcome of one round of close combat between two units.

    ``losses`` is the *joint* distribution of models removed **in the melee**:
    ``losses[j][k]`` = P(A lost j models and B lost k). The two sides are
    correlated whenever one strikes first — a side that lost heavily strikes
    back with fewer models — so the joint, not the two marginals, is what the
    scoring margin must be computed from. ``a_casualties`` and
    ``b_casualties`` are its marginals (melee only — a Stand & Shoot volley's
    casualties are reported on the volley itself). ``wound_margin`` is the
    signed distribution combat-result scoring reads (see :attr:`scoring_wounds`):
    the melee wound difference *plus* any Stand & Shoot wounds, which the
    rulebook counts toward the shooting side's combat result. ``first_striker``
    is the
    :class:`Contingent` that struck first by Initiative, or None when equal
    Initiative made the blows simultaneous. ``a_initiative`` and
    ``b_initiative`` are the effective Initiatives that ordering compared —
    reported so a caller prints the value the math used, as the shooting
    result reports its effective To Hit target. ``a_rank_bonus`` and
    ``b_rank_bonus`` are each side's combat-result Rank Bonus, which
    :func:`combat_result` adds to that side's score. ``a_unit_strength`` and
    ``b_unit_strength`` are the Unit Strengths the round compared (reported,
    and the basis of an outnumbering bonus). ``a_combat_result_bonus`` and
    ``b_combat_result_bonus`` are the rule-granted combat-result points each
    side accrued (Massed Infantry's +1, and later others) — a signed total
    :func:`combat_result` adds to the score alongside the Rank Bonus.
    """

    # Covariant, so a caller holding a list[list[float]] can pass it: list is
    # invariant, and these are read-only after construction.
    losses: Sequence[Sequence[Probability]]  # losses[a_lost][b_lost] = joint probability
    first_striker: Contingent | None
    notes: tuple[str, ...] = ()
    a_initiative: EffectiveValue = EffectiveValue(0)
    b_initiative: EffectiveValue = EffectiveValue(0)
    a_rank_bonus: int = 0
    b_rank_bonus: int = 0
    a_unit_strength: int = 0
    b_unit_strength: int = 0
    a_combat_result_bonus: int = 0
    b_combat_result_bonus: int = 0
    # The signed distribution of (A's minus B's) combat-result wounds, populated by
    # fight(); empty on a fixture-built result, which then scores off the melee
    # joint alone (see scoring_wounds).
    wound_margin: Mapping[int, Probability] = field(default_factory=dict)

    @property
    def a_casualties(self) -> list[Probability]:
        """Marginal distribution of models A lost in the melee (index k = P(k removed))."""
        return [sum(row) for row in self.losses]

    @property
    def b_casualties(self) -> list[Probability]:
        """Marginal distribution of models B lost in the melee (index k = P(k removed))."""
        columns = len(self.losses[0]) if self.losses else 0
        return [sum(row[k] for row in self.losses) for k in range(columns)]

    @property
    def scoring_wounds(self) -> Mapping[int, Probability]:
        """The signed distribution of (A's minus B's) combat-result wounds.

        Each side's wounds are the unsaved wounds it inflicted this round plus
        any it caused by a Stand & Shoot charge reaction this turn — the Wounds
        line of the combat-result score (a Stand & Shoot's wounds count for the
        shooter). :func:`fight` populates ``wound_margin`` with this, since only
        it holds the joint of the volley's thinning and the melee that thinning
        shaped. A FightResult built without it (a scoring fixture) falls back to
        the melee joint, scoring the round's wounds alone.

        Returns:
            The wound-difference pmf (A-positive), from ``wound_margin`` when
            populated, else derived from the melee ``losses``.
        """
        if self.wound_margin:
            return self.wound_margin
        derived: dict[int, Probability] = {}
        for a_lost, row in enumerate(self.losses):
            for b_lost, mass in enumerate(row):
                if mass:
                    diff = b_lost - a_lost
                    derived[diff] = derived.get(diff, 0) + mass
        return derived


def _unit_rule_notes(side: Contingent, claimed: Collection[str] = ()) -> list[str]:
    # The one owner of a unit rule's disposition: a rule the consumer could not
    # claim is reported "not factored"; a claimed rule that authored notes has
    # them relayed (Stubborn's scope caveats). Notes are built once, never
    # parsed. A rule printed on the datasheet is owned by the unit; one the
    # troop type confers (Press of Battle, ...) by the troop type.
    unit = side.unit
    troop_type = unit.troop_type_profile
    owned = [(printed, unit.name) for printed in unit.special_rules]
    if troop_type is not None:
        owned += [(printed, troop_type.name) for printed in troop_type.special_rules]
    unfactored = [
        f"special rule not factored: {printed} ({owner})"
        for printed, owner in owned
        if printed not in claimed
    ]
    return unfactored + factored_notes(
        side.loadout.rules, claimed, unit.name, side.loadout.granted_rules
    )


def _worn_in_combat(side: Contingent) -> "tuple[ArmourFacts, ...]":
    # What a side effectively wears in close combat: its pieces less what the
    # weapon in its hands bars (Requires Two Hands' shield). Filtered from the
    # facts as well as the folds, so a gate asking "using a shield" is told
    # the truth about a two-handed wielder.
    barred = barred_worn(side.in_hand_rules(), GateContext(combat=CombatFacts()))
    return tuple(facts for facts in side.armour_facts if facts.name not in barred.names)


def _weapon_rule_notes(engagement: _Engagement, claimed: Collection[str] = ()) -> list[str]:
    # The weapon rules this batch's walk could not factor, less what its own
    # seams claimed and what the ``claimed`` extra covers — in a full round,
    # the names the bearer's own defence consumed from the other walk's seat.
    return [
        f"weapon rule not factored: {rule} ({engagement.weapon_name})"
        for rule in engagement.offence.weapon_unfactored
        if rule not in engagement.weapon_claimed and rule not in claimed
    ]


def _combat_conditions(first_round: bool | None, side: Contingent, foe: Contingent) -> GateContext:
    # The gate facts for one side of the combat. ``first_round`` is the combat's
    # (a relational fact); ``outnumbers`` weighs the two sides' Unit Strength
    # (strictly greater — equal Unit Strength outnumbers neither); the movement
    # facts read the side's own state, the charge carrying its distance so a
    # gate can ask ``movement.charge.distance`` (Furious Charge's 3"). No shot
    # is taken in close combat, so the volley fact is settled False. The side
    # is engaged (``combat`` present) and is the target of the foe's close-combat
    # attack, magical if the foe's weapon in hand is — the facts Parry and Lion
    # Cloak read from the defender's side. The side's own equipment in use rides
    # along, so a rule gated on its gear (Parry's hand weapon and shield,
    # Ithilmar Weapons' hand weapon) is answered from the one context whichever
    # seam reads it — the dice walk, the armour fold, the re-roll fold.
    charge = side.movement.charge
    foe_weapon = foe.weapon
    foe_profile = foe_weapon.combat_profile if foe_weapon is not None else None
    foe_marks = attack_marks(
        foe_profile.special_rules if foe_profile is not None else [],
        foe.loadout.weapon_rules,
        foe.loadout.rules,
    )
    return GateContext(
        combat=CombatFacts(
            first_round=first_round,
            outnumbers=side.unit_strength() > foe.unit_strength(),
        ),
        movement=MovementFacts(
            moved=side.movement.moved,
            charge=ChargeEvent(distance=charge.full_inches) if charge is not None else None,
        ),
        shooting=ShootingFacts(at_long_range=False),
        wielding=side.weapon_facts,
        worn=_worn_in_combat(side),
        foe=FoeFacts(troop_type=foe.unit.troop_type),
        target_of=AttackFacts(
            kind=AttackKind.CLOSE_COMBAT,
            magical=foe_marks.magical,
            flaming=foe_marks.flaming,
        ),
    )


def effective_initiative(
    contingent: Contingent,
    charge_bonus: int = 0,
    conditions: "GateContext | None" = None,
) -> EffectiveValue:
    """The Initiative a contingent strikes at, all printed modifiers included.

    The striking-order assembler, and the one home of the Initiative
    ceiling: the rank-and-file Initiative, modified by the rule-granted
    characteristic modifiers under the evaluated ``conditions``, plus the
    ``charge_bonus`` the charge already arc-capped
    (:attr:`~avelorn.tow.contingent.Charge.initiative_bonus`), the total
    capped at 10 (the-combat-phase/charging-units). A profile with no
    printed Initiative counts as 0.

    The Initiative-setting rules fold from two sources: the unit's own
    loadout rules (Strike First, Elven Reflexes) and the rules on the
    weapon in hand (a great weapon's Strike Last), both weighed together —
    so a model with Strike First and a Strike Last weapon has the two
    cancel, exactly as if it printed both. The set lands before the
    additive modifiers and the charge bonus (Strike Last's I1 becomes I2
    for a charger), and a rule the walk cannot factor but the read can (a
    weapon's Strike Last) is claimed here so it is not reported unfactored.

    The charge reaches here once, and only as a number: its facts (that
    the charger moved) travel in ``conditions``, its Initiative
    contribution as ``charge_bonus`` — the :class:`Charge` object is not
    passed, so it cannot arrive twice.

    Returns:
        The Initiative that decides striking order in :func:`fight`,
        with the rule names factored into it and those left unfactored —
        the caller reports the latter.
    """
    base = contingent.unit.main[Characteristic.INITIATIVE] or 0
    rules = [*contingent.loadout.rules, *contingent.in_hand_rules()]
    modified = effective_characteristic(base, Characteristic.INITIATIVE, rules, conditions)
    return replace(modified, value=min(modified.value + charge_bonus, 10))


def mount_initiative(contingent: Contingent, charge_bonus: int = 0) -> EffectiveValue:
    """The Initiative a ridden contingent's mounts strike at.

    The mount row's own printed Initiative — a split profile's sets of
    Attacks each resolve when their value is reached
    (the-combat-phase/split-profiles-combat) — plus the ``charge_bonus`` the
    model's charge grants ("models gain a modifier to their Initiative",
    the-combat-phase/charging-units: the model's, so mount and rider alike),
    capped at 10. Rule-granted Initiative modifiers are not folded: the
    corpus's are the rider's own (Elven Reflexes prints "(but not its
    mount)"), and no schema word says which element a modifier reaches yet.

    Returns:
        The mounts' effective Initiative.

    Raises:
        ValueError: the contingent rides nothing.
    """
    mount = contingent.unit.mount
    if mount is None:
        raise ValueError(f"{contingent.unit.name} rides nothing; it has no mount Initiative")
    base = mount[Characteristic.INITIATIVE] or 0
    return EffectiveValue(min(base + charge_bonus, 10))


def effective_weapon_skill(
    contingent: Contingent,
    conditions: "GateContext | None" = None,
) -> EffectiveValue:
    """The Weapon Skill a contingent fights at, all printed modifiers included.

    The sibling of :func:`effective_initiative` for the To Hit chart: the
    rank-and-file Weapon Skill, modified by the loadout's rule-granted
    characteristic modifiers under the evaluated ``conditions`` (Martial
    Prowess's +1 in the first round of combat). A profile with no printed
    Weapon Skill counts as 0 — the caller validates that a fighter has one
    before reaching here. Read for both sides of a strike: the striker's own
    To Hit, and the target's WS the roll is made against.

    Returns:
        The effective Weapon Skill, with the rule names factored into it and
        those left unfactored — the caller reports the latter.
    """
    base = contingent.unit.main[Characteristic.WEAPON_SKILL] or 0
    return effective_characteristic(
        base, Characteristic.WEAPON_SKILL, contingent.loadout.rules, conditions
    )


def _prior_losses(pmf: Sequence[Probability] | None, models: int, name: str) -> Distribution[int]:
    # A side's pre-combat losses: P(k models lost before any blows are struck).
    # None means none were lost -- certainty at zero. A side cannot lose more
    # models than it fields, and the mass must be a distribution.
    if pmf is None:
        return Distribution.pure(0)
    if len(pmf) > models + 1:
        raise ValueError(f"{name} covers more losses ({len(pmf) - 1}) than models ({models})")
    if any(p < 0 for p in pmf):
        raise ValueError(f"{name} has a negative probability")
    if not isclose(sum(pmf), 1.0):
        raise ValueError(f"{name} must sum to 1, got {sum(pmf)}")
    return Distribution.from_counts(pmf)


class _Priors(NamedTuple):
    # What each side lost before any blows were struck. The two thinnings are
    # independent, so one branch of their joint is a pair.
    a: int
    b: int


class _RoundOutcome(NamedTuple):
    # One whole branch of a round: what each side had already lost before blows
    # (a Stand & Shoot volley on the chargers) and what the melee then removed.
    # The four travel together because they are correlated — the volley that
    # felled ``pre_a`` of A both lightens A's return blows and scores for B -- and
    # every figure fight() reports is a relabel of this one joint.
    pre_a: int
    pre_b: int
    a_lost: int
    b_lost: int


def _loss_grid(
    melee: Distribution[tuple[int, int]], a_models: int, b_models: int, zero: Probability
) -> list[list[Probability]]:
    # The melee joint as the grid FightResult publishes: grid[a_lost][b_lost].
    # Cells no outcome reaches keep a zero of the round's own numeric kind, so an
    # exact round stays exact across the whole grid (see _remove_casualties).
    grid: list[list[Probability]] = [[zero] * (b_models + 1) for _ in range(a_models + 1)]
    for (a_lost, b_lost), mass in melee.mass.items():
        grid[a_lost][b_lost] = mass
    return grid


def fight(
    a: Contingent,
    b: Contingent,
    *,
    a_prior_losses: Sequence[Probability] | None = None,
    b_prior_losses: Sequence[Probability] | None = None,
    first_round: bool | None = None,
    phase_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
) -> FightResult:
    """Resolve one round of close combat between two units.

    Each side fights with the weapon it has in hand (``a.in_hand()`` /
    ``b.in_hand()``), the one it was armed with through
    :meth:`~avelorn.tow.contingent.Contingent.wielding` — a per-side choice,
    since a unit may carry several (a hand weapon and a great weapon) and
    picks one to swing. A ridden unit's mounts fight beside their riders as
    a second batch of attacks — the mount row's own Weapon Skill, Strength
    and Attacks, swinging the hooves that count as a hand weapon
    (troop-types-in-detail/split-profile-cavalry) — resolved at the mount
    row's own Initiative.

    Striking order walks the batches' Initiative values from highest to
    lowest: batches at a value strike together, their casualties are removed,
    and lower batches strike **with the survivors** — so the loser of an
    exchange swings back with fewer models, and a model slain before its
    mounts' lower Initiative is reached loses those attacks
    (the-combat-phase: who-strikes-first, fight-on, split-profiles-combat).
    Batches at equal Initiative strike simultaneously, with no such
    reduction (simultaneous-combat). ``first_striker`` compares the sides'
    rank-and-file Initiatives, as before.

    Each side's own charge (``a.movement.charge`` / ``b.movement.charge``)
    adds its Initiative bonus before the comparison (the-combat-phase/charging-units),
    the modified Initiative capped at 10. ``first_round`` — whether this is
    the combat's first round — is the round's own relational fact, not
    either unit's, so it is a parameter here. The two sides are otherwise
    symmetric; only Initiative orders them. Resolution happens in strike
    order and the joint is oriented back to the ``(a, b)`` axes the caller
    passed.

    ``phase_rules`` are the combat chapter's rules in force — resolved by
    printed name, they apply to every strike this round, gated by each
    side's conditions, exactly as a volley's shooting-phase rules do
    (:func:`~avelorn.tow.phases.shooting.shoot_unit`). The Game assembles
    the mapping once (``game.in_play``); omitted, no chapter rule is in
    force and none is factored.

    ``a_prior_losses`` / ``b_prior_losses`` let a side enter already thinned:
    a pmf whose index ``k`` is P(that side lost ``k`` models *before* any
    blows — a Stand & Shoot volley on the chargers, say). The round is
    resolved at each surviving strength and mixed over these two
    (independent) distributions, exactly; omitted, a side enters at full
    ``models``. The returned ``losses`` count only this round's melee
    casualties (a Stand & Shoot volley's casualties are reported on the volley),
    but its wounds *do* score: a Stand & Shoot's unsaved wounds count toward the
    shooting side's combat result (rulebook), so ``fight`` credits a side's
    pre-melee (prior) losses to its foe in ``wound_margin`` — the distribution
    :func:`combat_result` scores — correlated with the same thinning they cause.

    Rule-granted characteristic modifiers apply to the striking order
    through the loadout of a contingent fielded with deploy(), gated on
    the side's facts; one left unevaluated stays noted. They fold from the
    unit's own rules (Elven Reflexes's +1 in the first round, Strike
    First) and from the weapon in hand (a great weapon's Strike Last) —
    Strike First / Strike Last set Initiative to 10 / 1 before those
    modifiers apply, and a model whose unit and weapon supply both has
    them cancel, since two rules setting the same characteristic to
    different values wash out. Deferred and noted, not modelled here: the
    Initiative bonus a Thrusting Spear grants when charged in its front
    arc — printed as free-text weapon notes, not a structured rule, so it
    stays surfaced in the notes; the supporting attacks Fight in Extra
    Rank / Martial Prowess grant the rank behind, split-profile champions
    (#46), and multi-unit combats. Each side fights with its fighting rank only — the
    front rank in base contact (:meth:`~avelorn.tow.contingent.Contingent.melee_attacks`),
    the whole front rank taken to be engaged (an equally wide foe). Score the
    round with :func:`combat_result`.

    Returns:
        The joint distribution of casualties for the round, oriented so
        ``losses[a_lost][b_lost]`` matches the contingents as passed.

    Raises:
        ValueError: either model count is negative, or a prior-loss pmf
            covers more losses than the side has models, carries a negative
            probability, or does not sum to 1 (plus the matchup errors
            raised by the underlying resolution).
    """
    if a.models < 0 or b.models < 0:
        raise ValueError("model counts must be >= 0")
    a_lost_before = _prior_losses(a_prior_losses, a.models, "a_prior_losses")
    b_lost_before = _prior_losses(b_prior_losses, b.models, "b_prior_losses")
    # Each side's engagement conditions, evaluated once: the same facts
    # gate its strike's dice walk (weapon and chapter rules) and its
    # striking-order Initiative — no fact is computed for one and denied
    # the other.
    a_conditions = _combat_conditions(first_round, a, b)
    b_conditions = _combat_conditions(first_round, b, a)
    a_strikes = _engage(
        a,
        b,
        hit_modifier=0,
        conditions=a_conditions,
        target_conditions=b_conditions,
        phase_rules=phase_rules,
    )
    b_strikes = _engage(
        b,
        a,
        hit_modifier=0,
        conditions=b_conditions,
        target_conditions=a_conditions,
        phase_rules=phase_rules,
    )
    a_mount_strikes = _mount_engage(
        a, b, conditions=a_conditions, target_conditions=b_conditions, phase_rules=phase_rules
    )
    b_mount_strikes = _mount_engage(
        b, a, conditions=b_conditions, target_conditions=a_conditions, phase_rules=phase_rules
    )
    a_bonus = 0 if a.movement.charge is None else a.movement.charge.initiative_bonus
    b_bonus = 0 if b.movement.charge is None else b.movement.charge.initiative_bonus
    a_initiative = effective_initiative(a, a_bonus, a_conditions)
    b_initiative = effective_initiative(b, b_bonus, b_conditions)
    a_first = _strikes_first(a_initiative.value, b_initiative.value)
    # Each side's batches at the Initiative each strikes at: the rank and
    # file at the side's effective Initiative, the mounts — a second set of
    # attacks the walk resolves when their value is reached
    # (the-combat-phase/split-profiles-combat) — at the mount row's own.
    a_batches: list[tuple[int, _Engagement | _AutomaticEngagement]] = [
        (a_initiative.value, a_strikes)
    ]
    if a_mount_strikes is not None:
        a_batches.append((mount_initiative(a, a_bonus).value, a_mount_strikes))
    b_batches: list[tuple[int, _Engagement | _AutomaticEngagement]] = [
        (b_initiative.value, b_strikes)
    ]
    if b_mount_strikes is not None:
        b_batches.append((mount_initiative(b, b_bonus).value, b_mount_strikes))
    # The automatic-hits batches a side's rules land outside the Initiative
    # order (Impact Hits, Stomp Attacks), each at its printed point of the
    # round — the sentinel steps the walk sorts with every other batch. The
    # folds come back whole so each side claims what they factored below.
    a_hits_folds: list[EffectiveHits] = []
    b_hits_folds: list[EffectiveHits] = []
    for batches, folds, side, foe, conditions, foe_conditions in (
        (a_batches, a_hits_folds, a, b, a_conditions, b_conditions),
        (b_batches, b_hits_folds, b, a, b_conditions, a_conditions),
    ):
        for order, step in ((HitOrder.FIRST, _OPENING_STEP), (HitOrder.LAST, _CLOSING_STEP)):
            batch, fold = _automatic_engage(
                side, foe, order, conditions=conditions, target_conditions=foe_conditions
            )
            folds.append(fold)
            if batch is not None:
                batches.append((step, batch))
    # Each side's rule-granted combat-result points, summed under its facts
    # (Massed Infantry's +1 when it outnumbers): folded here, added to the
    # score in combat_result, and claimed out of the notes below.
    a_combat_result = effective_combat_result_bonus(a.loadout.rules, a_conditions)
    b_combat_result = effective_combat_result_bonus(b.loadout.rules, b_conditions)

    # Each side may enter already thinned by pre-combat casualties (a Stand &
    # Shoot volley, say). The two thinnings are independent, so their joint is
    # combine; the round is then the melee resolved at whatever strengths each
    # branch left, tagged with the priors that produced it.
    priors = a_lost_before.combine(b_lost_before, _Priors)
    outcomes = priors >> (
        lambda pre: _round_joint(a_batches, a.models - pre.a, b_batches, b.models - pre.b).map(
            lambda lost: _RoundOutcome(pre.a, pre.b, *lost)
        )
    )
    # Both figures fight() reports are relabels of that one joint. ``losses``
    # keeps the melee alone, since a Stand & Shoot volley's casualties are
    # reported on the volley. ``wound_margin`` is the combat-result wound
    # difference, which counts the volley's wounds too: a side's pre-melee losses
    # were the *other* side's volley, so they credit that other side (rulebook:
    # unsaved wounds inflicted, including by a Stand & Shoot this turn). Reading
    # both off the same outcomes is what keeps the credit correlated with the
    # thinning it caused. (Counts models removed, = wounds for the 1-Wound models
    # the engine fields; a multi-Wound Stand & Shoot would credit wounds, not
    # casualties.)
    zero = (a_strikes.p_unsaved + b_strikes.p_unsaved) * 0
    losses = _loss_grid(outcomes.map(lambda o: (o.a_lost, o.b_lost)), a.models, b.models, zero)
    wound_margin = outcomes.map(lambda o: (o.b_lost + o.pre_b) - (o.a_lost + o.pre_a)).mass

    first_striker = None if a_first is None else (a if a_first else b)
    # A rule factored into the striking order, the fighting-rank depth, the
    # effective Attacks, or the effective Weapon Skill is in the math — claimed,
    # so never noted; both sides strike, so each claims its own. A mirror match
    # dedups the identical remainder. Both seats of both walks are resolved
    # here, so each side also claims what the seat it did not compile from
    # skipped as inapplicable: whatever one seat is not the business of, the
    # other seat's compile has.
    # A side's mount batch reads the same rules from its own seat (the mount's
    # weapon in hand), so what its walk factored is claimed alongside the rank
    # and file's; a side with no mount contributes empty sets.
    a_own = [s for s in (a_strikes, a_mount_strikes) if s is not None]
    b_own = [s for s in (b_strikes, b_mount_strikes) if s is not None]
    notes = tuple(
        dict.fromkeys(
            [
                *_unit_rule_notes(
                    a,
                    claimed={
                        *a_initiative.factored,
                        *a.fighting_ranks().factored,
                        *a.effective_attacks().factored,
                        *(name for s in a_own for name in s.weapon_skill.factored),
                        *(name for s in a_own for name in s.offence.rerolls.factored),
                        *(name for s in a_own for name in s.offence.rerolls.inapplicable),
                        *(name for s in a_own for name in s.offence.factored),
                        *(name for s in a_own for name in s.offence.inapplicable),
                        *(name for fold in a_hits_folds for name in fold.factored),
                        *a_combat_result.factored,
                        # a's defensive rules are read while it is b's target
                        *(name for s in b_own for name in s.defence.armour.factored),
                        *(name for s in b_own for name in s.defence.ward.factored),
                        *(name for s in b_own for name in s.defence.rerolls.factored),
                        *(name for s in b_own for name in s.defence.rerolls.inapplicable),
                        *(name for s in b_own for name in s.defence.factored),
                        *(name for s in b_own for name in s.defence.inapplicable),
                    },
                ),
                *_unit_rule_notes(
                    b,
                    claimed={
                        *b_initiative.factored,
                        *b.fighting_ranks().factored,
                        *b.effective_attacks().factored,
                        *(name for s in b_own for name in s.weapon_skill.factored),
                        *(name for s in b_own for name in s.offence.rerolls.factored),
                        *(name for s in b_own for name in s.offence.rerolls.inapplicable),
                        *(name for s in b_own for name in s.offence.factored),
                        *(name for s in b_own for name in s.offence.inapplicable),
                        *(name for fold in b_hits_folds for name in fold.factored),
                        *b_combat_result.factored,
                        *(name for s in a_own for name in s.defence.armour.factored),
                        *(name for s in a_own for name in s.defence.ward.factored),
                        *(name for s in a_own for name in s.defence.rerolls.factored),
                        *(name for s in a_own for name in s.defence.rerolls.inapplicable),
                        *(name for s in a_own for name in s.defence.factored),
                        *(name for s in a_own for name in s.defence.inapplicable),
                    },
                ),
                *(
                    note
                    for s in a_own
                    for note in _weapon_rule_notes(
                        s, claimed=[n for o in b_own for n in o.defence.weapon_factored]
                    )
                ),
                *(
                    note
                    for s in b_own
                    for note in _weapon_rule_notes(
                        s, claimed=[n for o in a_own for n in o.defence.weapon_factored]
                    )
                ),
                *(note for s in a_own for note in s.notes),
                *(note for s in b_own for note in s.notes),
            ]
        )
    )
    logger.debug(
        "fight: %s vs %s, first=%s",
        a.unit.name,
        b.unit.name,
        "simultaneous" if first_striker is None else first_striker.unit.name,
    )
    return FightResult(
        losses=losses,
        first_striker=first_striker,
        notes=notes,
        a_initiative=a_initiative,
        b_initiative=b_initiative,
        a_rank_bonus=a.rank_bonus,
        b_rank_bonus=b.rank_bonus,
        a_unit_strength=a.unit_strength(),
        b_unit_strength=b.unit_strength(),
        a_combat_result_bonus=a_combat_result.value,
        b_combat_result_bonus=b_combat_result.value,
        wound_margin=wound_margin,
    )


def _fell(
    engagements: "Sequence[_Engagement | _AutomaticEngagement]", fighters: int, *, targets: int
) -> Distribution[int]:
    # Casualties inflicted on the target by ``fighters`` models striking, over
    # every batch the models throw at this step (a lone rank-and-file batch,
    # or riders and mounts sharing an Initiative). Each batch's attack count
    # is a distribution — certain for a printed Attacks value, dice-driven for
    # an automatic-hits batch — so the counts' joint mixes over the batched
    # fold: wounds pool before the fold to models and the size cap, the
    # unit-level steps. Zero-mass counts drop on the way in, which is what
    # lets the folds below skip unreachable branches without testing for them.
    if not engagements:
        return Distribution.pure(0)
    counts: Distribution[tuple[int, ...]] = Distribution.pure(())
    for engagement in engagements:
        counts = counts.combine(engagement.attack_counts(fighters), lambda ns, n: (*ns, n))

    def felled(ns: tuple[int, ...]) -> Distribution[int]:
        batches = [
            AttackBatch(n, p_unsaved=e.p_unsaved, p_kill=e.p_kill)
            for e, n in zip(engagements, ns, strict=True)
        ]
        _, casualties = batched_wound_and_casualties(
            batches,
            wounds_per_model=engagements[0].target_wounds,
            targets=targets,
        )
        return Distribution.from_counts(casualties)

    return counts >> felled


def _strikes_first(initiative_a: int, initiative_b: int) -> bool | None:
    # Who strikes first by Initiative: True if A does, False if B, None when
    # equal Initiative makes the blows simultaneous.
    if initiative_a == initiative_b:
        return None
    return initiative_a > initiative_b


# One side's attack batches, each at the Initiative it strikes at: the
# rank-and-file batch, plus the mount batch for a ridden unit, plus any
# automatic-hits batch a rule lands outside the Initiative order. The round
# walks the Initiative values downward and resolves every batch when its
# value is reached (the-combat-phase/who-strikes-first; split-profiles-combat).
_Batches = Sequence[tuple[int, "_Engagement | _AutomaticEngagement"]]

# Where the automatic-hits batches land in that walk. Effective Initiative is
# capped at 10 and floored at 0, so the sentinels sort clear of every real
# step: Impact Hits ahead of them all — "resolved against the charged unit
# when the combat is chosen ... before issuing challenges" — and Stomp
# Attacks after them all — "must be made last, after all other attacks have
# been made, including attacks made at Initiative 1".
_OPENING_STEP = 11
_CLOSING_STEP = -1


class _Alive(NamedTuple):
    # The models each side still has standing mid-round, the state the
    # Initiative walk threads: batches yet to strike swing from these counts.
    a: int
    b: int


def _round_joint(
    a_batches: _Batches,
    a_models: int,
    b_batches: _Batches,
    b_models: int,
) -> Distribution[tuple[int, int]]:
    # One round's joint casualty distribution at fixed model counts, over
    # outcomes (a_lost, b_lost). The printed sequence: walk the Initiative
    # values from highest to lowest; batches at the same value strike
    # simultaneously (independent losses), casualties are removed, and lower
    # batches strike from whatever remains (fight-on) — a model slain before
    # its lower-Initiative batch strikes loses those attacks
    # (the-combat-phase/split-profiles-combat).
    state = Distribution.pure(_Alive(a_models, b_models))
    for step in sorted({i for i, _ in (*a_batches, *b_batches)}, reverse=True):
        a_now = [e for i, e in a_batches if i == step]
        b_now = [e for i, e in b_batches if i == step]
        state = state >> (lambda alive, a_now=a_now, b_now=b_now: _step_joint(alive, a_now, b_now))
    return state.map(lambda alive: (a_models - alive.a, b_models - alive.b))


def _step_joint(
    alive: _Alive,
    a_now: "Sequence[_Engagement | _AutomaticEngagement]",
    b_now: "Sequence[_Engagement | _AutomaticEngagement]",
) -> Distribution[_Alive]:
    # One Initiative step from one branch of the round: every batch whose value
    # is reached strikes at once, from the models its side still has, so the two
    # sides' losses this step are independent — the outer product combine takes.
    b_losses = _fell(a_now, alive.a, targets=alive.b)
    a_losses = _fell(b_now, alive.b, targets=alive.a)
    return a_losses.combine(
        b_losses, lambda a_lost, b_lost: _Alive(alive.a - a_lost, alive.b - b_lost)
    )


_UNMODELLED_COMBAT_RESULT: tuple[str, ...] = (
    "combat result component not factored: standards (#28)",
    "combat result component not factored: flank & rear attacks (#28)",
    "combat result component not factored: the high ground (#28)",
    "combat result component not factored: overkill (#28)",
)


@dataclass(frozen=True)
class CombatResult:
    """Who won a round of close combat, scored on unsaved wounds inflicted.

    ``margin`` maps a signed lead ``m`` to P(A's score - B's score == m);
    positive means A is ahead. A side's score is the unsaved wounds it
    inflicted plus its Rank Bonus and any rule-granted combat-result points
    (Massed Infantry's outnumbering +1); the components still unmodelled are
    listed in ``notes`` (#28). For 1-Wound models wounds inflicted equal
    models removed; the wound-count for multi-Wound models is not modelled.
    The signed ``margin`` is what the Break test adds to the loser's roll.
    """

    p_a_wins: Probability
    p_draw: Probability
    p_b_wins: Probability
    margin: Mapping[int, Probability]
    notes: tuple[str, ...] = ()


def combat_result(result: FightResult) -> CombatResult:
    """Score a fought round by unsaved wounds inflicted and name the winner.

    Composes on a :class:`FightResult`'s :attr:`~FightResult.scoring_wounds`:
    A's score is the unsaved wounds it inflicted — this round's melee plus any
    from a Stand & Shoot charge reaction this turn — plus A's Rank Bonus and
    rule-granted combat-result points, B's the reverse. The Rank Bonus and
    points are fixed for the round, so they shift every lead by the same
    constant. Because the two sides are correlated (under Initiative order, and
    through a volley that both thins a side and scores for its foe), the
    win/draw/win split and signed margin come from the joint wound distribution,
    not from differencing marginals.

    Returns:
        The exact win/draw/loss probabilities and signed margin distribution.
    """
    margin: Mapping[int, Probability] = {}
    p_a_wins = p_draw = p_b_wins = 0
    # A's fixed edge over B: Rank Bonus plus the rule-granted combat-result
    # points (Massed Infantry, ...), each a signed per-side constant that
    # shifts every lead alike. The wound difference (melee + Stand & Shoot)
    # carries the rest.
    static_delta = (result.a_rank_bonus - result.b_rank_bonus) + (
        result.a_combat_result_bonus - result.b_combat_result_bonus
    )
    for wound_diff, mass in result.scoring_wounds.items():
        if mass == 0:
            continue
        lead = wound_diff + static_delta
        margin[lead] = margin.get(lead, 0) + mass
        if lead > 0:
            p_a_wins += mass
        elif lead < 0:
            p_b_wins += mass
        else:
            p_draw += mass
    logger.debug("combat result: P(a)=%.3f draw=%.3f P(b)=%.3f", p_a_wins, p_draw, p_b_wins)
    return CombatResult(
        p_a_wins=p_a_wins,
        p_draw=p_draw,
        p_b_wins=p_b_wins,
        margin=margin,
        notes=_UNMODELLED_COMBAT_RESULT,
    )


@dataclass(frozen=True)
class SideBreak:
    """A side's Break-test outcomes for the rounds it loses.

    Only the losing side takes a Break test, so these are the printed
    outcomes for this side *conditioned on it being the loser*: the three
    sum to the probability this side lost the round. The winner takes no
    Break test — its follow-up / pursuit / reform choices are not modelled
    here.
    """

    p_gives_ground: Probability
    p_falls_back: Probability
    p_breaks: Probability


@dataclass(frozen=True)
class BreakResult:
    """Both sides' Break-test outcomes for one round of close combat.

    A round has at most one loser, so ``a`` and ``b`` are mutually
    exclusive — each is non-zero only across the outcomes where that side
    lost. ``p_draw`` is the chance of a drawn combat, in which neither side
    tests. The two sides' six outcome probabilities and ``p_draw`` sum to 1.
    ``notes`` surface what a rule that fixed an outcome (Stubborn) did and the
    parts of it the current scope does not model.
    """

    a: SideBreak
    b: SideBreak
    p_draw: Probability
    notes: tuple[str, ...] = ()


def break_test(result: CombatResult, a: Contingent, b: Contingent) -> BreakResult:
    """Resolve the Break test for a scored combat round, for each side.

    Only the losing side rolls: 2D6, add the winner's margin, compare to
    its Leadership (highest value in the unit). A natural roll above
    Leadership Breaks and flees; a natural roll within it but a modified
    roll above Falls Back in Good Order; a modified roll within it — or a
    natural double 1 — Gives Ground (the-combat-phase/break-test). The
    winner takes no Break test (its follow-up and pursuit choices are not
    modelled here), and a drawn combat tests neither side.

    A side's resolved rules may force its outcome instead of rolling: Stubborn's
    :class:`~avelorn.tow.schema.rule.ChoiceEffect` sends its whole losing mass to
    Fall Back in Good Order (it never Breaks). What that model leaves out — the
    once-per-battle limit, the option to decline, the forgone Give Ground — is
    returned in :attr:`BreakResult.notes`, not silently applied.

    Composes on the signed margin distribution: ``a`` is the positive-margin
    side, matching :func:`fight`'s ``a``; each contingent supplies its
    Leadership (highest in the unit) and its resolved rules.

    Returns:
        Each side's Break-test outcomes for the rounds it loses, the
        drawn-combat probability, and the notes for any fixed-outcome rule.
    """
    a_leadership = a.unit.highest(Characteristic.LEADERSHIP) or 0
    b_leadership = b.unit.highest(Characteristic.LEADERSHIP) or 0
    # The break decision's outcomes are BreakOutcomes; narrow the base the seam
    # returns to the set this test routes (a foreign outcome under break, a data
    # slip, is left to roll).
    a_outcome, a_rule = forced_outcome(a.loadout.rules, Decision.BREAK)
    b_outcome, b_rule = forced_outcome(b.loadout.rules, Decision.BREAK)
    a_forced = a_outcome if isinstance(a_outcome, BreakOutcome) else None
    b_forced = b_outcome if isinstance(b_outcome, BreakOutcome) else None
    # A rule may instead replace one rolled outcome with another (Shieldwall's
    # Give Ground rather than Fall Back in Good Order), gated on the break's
    # own facts: whether the side was charged this turn (the foe's move) and
    # what it effectively wears beside the weapon in its hands — a two-handed
    # wielder's shield is withdrawn, so its wall never forms.
    a_swaps, a_swap_rules = _break_substitutions(a, b)
    b_swaps, b_swap_rules = _break_substitutions(b, a)
    logger.debug(
        "break test: Ld %d (a, forced=%s) vs Ld %d (b, forced=%s)",
        a_leadership,
        a_forced,
        b_leadership,
        b_forced,
    )
    # Relay the fixed-outcome rule's own authored notes (its unmodelled scope),
    # the same generic relay every seam shares — never engine-composed prose.
    a_claimed = sorted({rule.name for rule in (a_rule, *a_swap_rules) if rule is not None})
    b_claimed = sorted({rule.name for rule in (b_rule, *b_swap_rules) if rule is not None})
    notes = tuple(
        dict.fromkeys(
            note
            for side, claimed in ((a, a_claimed), (b, b_claimed))
            for name in claimed
            for note in factored_notes(
                side.loadout.rules, {name}, side.unit.name, side.loadout.granted_rules
            )
        )
    )
    return BreakResult(
        a=_side_break(
            result.margin,
            a_leadership,
            deficit=lambda lead: -lead if lead < 0 else None,
            forced=a_forced,
            substitutions=a_swaps,
        ),
        b=_side_break(
            result.margin,
            b_leadership,
            deficit=lambda lead: lead if lead > 0 else None,
            forced=b_forced,
            substitutions=b_swaps,
        ),
        p_draw=sum(mass for lead, mass in result.margin.items() if lead == 0),
        notes=notes,
    )


def _break_substitutions(
    side: Contingent, foe: Contingent
) -> tuple[dict[BreakOutcome, BreakOutcome], list[Rule]]:
    # The side's outcome substitutions at its Break test, under the break's
    # own facts. Only Break outcomes route here; a foreign outcome in the
    # data is left to roll, as a foreign forced outcome is.
    conditions = GateContext(
        combat=CombatFacts(was_charged=foe.movement.charge is not None),
        wielding=side.weapon_facts,
        worn=_worn_in_combat(side),
    )
    swaps: dict[BreakOutcome, BreakOutcome] = {}
    rules: list[Rule] = []
    for replaced, taken, rule in outcome_substitutions(
        side.loadout.rules, Decision.BREAK, conditions
    ):
        if isinstance(replaced, BreakOutcome) and isinstance(taken, BreakOutcome):
            swaps.setdefault(replaced, taken)
            rules.append(rule)
    return swaps, rules


def _side_break(
    margin: Mapping[int, Probability],
    leadership: int,
    *,
    deficit: Callable[[int], int | None],
    forced: BreakOutcome | None = None,
    substitutions: Mapping[BreakOutcome, BreakOutcome] | None = None,
) -> SideBreak:
    # Aggregate one side's Break-test outcomes over the rounds it loses.
    # ``deficit(lead)`` is this side's losing margin at signed lead ``lead``,
    # or None when it did not lose (it won, or the combat was drawn) and so
    # takes no test. ``forced`` fixes the outcome (Stubborn): the whole losing
    # mass goes to that result rather than the rolled split. ``substitutions``
    # then replace one outcome with another (Shieldwall's Give Ground rather
    # than Fall Back in Good Order) — applied after the force, so a Stubborn
    # Shieldwall unit falls back only where its wall does not hold.
    outcomes: dict[BreakOutcome, Probability] = {outcome: 0 for outcome in BreakOutcome}
    for lead, mass in margin.items():
        loss = deficit(lead)
        if loss is None:
            continue
        if forced is not None:
            outcomes[forced] += mass
        else:
            p_break, p_fall, p_give = _break_outcomes(leadership, loss)
            outcomes[BreakOutcome.BREAKS] += mass * p_break
            outcomes[BreakOutcome.FALLS_BACK] += mass * p_fall
            outcomes[BreakOutcome.GIVES_GROUND] += mass * p_give
    for replaced, taken in (substitutions or {}).items():
        outcomes[taken] += outcomes[replaced]
        outcomes[replaced] = 0
    return SideBreak(
        p_gives_ground=outcomes[BreakOutcome.GIVES_GROUND],
        p_falls_back=outcomes[BreakOutcome.FALLS_BACK],
        p_breaks=outcomes[BreakOutcome.BREAKS],
    )


def _break_outcomes(leadership: int, margin: int) -> tuple[Probability, Probability, Probability]:
    # The three Break-test outcome probabilities for a loser of ``leadership``
    # facing a winner's ``margin`` (>= 1), over an exact 2D6. A natural
    # double 1 always Gives Ground; otherwise a natural roll over Leadership
    # Breaks, a modified roll over it Falls Back, and the rest Gives Ground.
    breaks = falls_back = gives_ground = 0
    for first, second in product(range(1, 7), repeat=2):
        natural = first + second
        if natural == 2:  # natural double 1
            gives_ground += 1
        elif natural > leadership:
            breaks += 1
        elif natural + margin > leadership:
            falls_back += 1
        else:
            gives_ground += 1
    # Exact: these are counts of 36 equally likely 2D6 outcomes, so a rational
    # says it precisely where a division would round it.
    return Fraction(breaks, 36), Fraction(falls_back, 36), Fraction(gives_ground, 36)


@dataclass(frozen=True)
class CombatPhase(Phase):
    """The Combat phase: its steps, its round's actions.

    ``in_play`` are the chapter's rules in force — every round of combat
    resolves under them, gated by each side's engagement conditions. No
    combat chapter rule carries effects in the data today, so the mapping
    is empty in practice; the path is here, so a rule gaining effects is a
    data change, honoured like its shooting sibling, not new code.
    """

    in_play: Mapping[str, Rule]

    # The printed combat sequence's modelled steps: every step knows
    # what it rolls — this Roll to Hit never confirms (a natural 6
    # always hits). The phase's other printed steps (choose combats,
    # calculate combat result, break tests) join when modelled, each as
    # a step that knows how it resolves.
    steps: ClassVar[tuple[type[Roll], ...]] = (
        RollToHitCombat,
        RollToWound,
        ArmourSave,
        WardSave,
    )

    @overload
    def fight(self, combat: Engagement, /) -> FightResult: ...

    @overload
    def fight(self, combat: Contingent, opponent: Contingent, /) -> FightResult: ...

    def fight(
        self,
        combat: Engagement | Contingent,
        opponent: Contingent | None = None,
        /,
    ) -> FightResult:
        """One round of a combat, under the chapter's rules in force.

        ``combat`` is either an :class:`~avelorn.tow.phases.movement.Engagement`
        — a charge-formed combat carrying the charge Initiative bonus, its
        first-round status, and any Stand & Shoot casualties — or two
        contingents in base contact, taken as a plain frontal standing combat:
        no charge, not a first round (the "or something else" opening). Each
        side swings the weapon it has in hand, armed through
        :meth:`~avelorn.tow.contingent.Contingent.wielding`.

        Returns:
            The round's joint casualty distribution.

        Raises:
            ValueError: a lone contingent with no opponent and no engagement.
        """
        if isinstance(combat, Engagement):
            a, b = combat.a, combat.b
            a_prior_losses = None if combat.reaction is None else combat.reaction.casualties
            first_round = combat.first_round
        elif opponent is None:
            raise ValueError("fighting two contingents needs both; pass an Engagement otherwise")
        else:
            a, b = combat, opponent
            a_prior_losses = None
            first_round = None
        return fight(
            a,
            b,
            a_prior_losses=a_prior_losses,
            first_round=first_round,
            phase_rules=self.in_play,
        )

    def result(self, fought: FightResult) -> CombatResult:
        """Score a fought round and name the winner.

        Returns:
            The win/draw/loss probabilities and signed margin.
        """
        return combat_result(fought)

    def break_test(self, scored: CombatResult, a: Contingent, b: Contingent) -> BreakResult:
        """The Break test for a scored round, for each side.

        Each contingent supplies its Leadership and its resolved rules (a
        fixed-outcome rule like Stubborn is read here).

        Returns:
            Each side's break outcome distribution, plus any fixed-outcome notes.
        """
        return break_test(scored, a, b)
