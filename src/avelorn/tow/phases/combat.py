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
from dataclasses import dataclass, replace
from itertools import product
from math import isclose
from typing import ClassVar, assert_never, overload

from avelorn.core.dice import expected_value
from avelorn.core.game import Phase
from avelorn.tow.contingent import Contingent
from avelorn.tow.engine.armour import defender_armour
from avelorn.tow.engine.attack import (
    ArmourSave,
    AttackProfile,
    Modifier,
    Outcome,
    Roll,
    RollToHitCombat,
    RollToWound,
    Transform,
    WardSave,
    resolve_attack,
    roll_target,
)
from avelorn.tow.engine.casualties import wound_and_casualties
from avelorn.tow.engine.charts import (
    armour_save_target,
    melee_hit_probability,
    melee_hit_target,
    save_probability,
    wound_probability,
    wound_target,
)
from avelorn.tow.engine.rules import (
    EffectiveCharacteristic,
    compile_rules,
    effective_characteristic,
)
from avelorn.tow.phases.movement import Engagement
from avelorn.tow.schema.rule import Condition, Rule
from avelorn.tow.schema.unit import Characteristic, Unit

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


def _per_attack(
    hit: int,
    wound: int | None,
    save: int | None,
    ward: int | None,
    modifiers: Sequence[Modifier],
    transforms: Sequence[Transform] = (),
) -> tuple[float, float, int]:
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
    )
    effective = resolution.hit_target if isinstance(resolution.hit_target, int) else hit
    return float(resolution.p_unsaved), float(resolution.p_of(Outcome.INSTANT_KILL)), effective


@dataclass(frozen=True)
class _Engagement:
    """One side's per-attack resolution against a specific foe.

    The matchup-dependent, fighter-count-independent half of a melee
    strike: the per-attack probabilities and reported targets, the
    ``striker`` throwing the blows, and the target's Wounds. The dice
    walk depends only on the matchup, so it runs once; :meth:`attacks` then
    turns any surviving strength into that many blows (its fighting rank)
    and :func:`wound_and_casualties` into a casualty distribution — the same
    walk serves a return strike whose numbers depend on casualties already
    taken.
    """

    striker: Contingent
    p_unsaved: float
    p_kill: float
    target_wounds: int
    hit_target: int
    wound_target: int | None
    save_target: int | None
    p_hit: float
    p_wound: float
    notes: tuple[str, ...]

    def attacks(self, survivors: int) -> int:
        """The blows ``survivors`` of the striking models throw this round.

        The striker reduced to its ``survivors`` throws its fighting rank
        (:meth:`~avelorn.tow.contingent.Contingent.melee_attacks`) — its full
        frontage until losses cut past the rear ranks into the front one, and
        the narrowed front thereafter — so a body thinned to fewer than a rank
        swings back with fewer attacks.

        Returns:
            The number of attacks thrown.
        """
        thinned = self.striker.remove_casualties(self.striker.models - survivors)
        return thinned.melee_attacks()


def _engage(
    striker: Contingent,
    target: Contingent,
    *,
    hit_modifier: int,
    conditions: Mapping[Condition, bool | None] | None = None,
    phase_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
) -> _Engagement:
    # The matchup half of a strike, shared by strike_unit and fight:
    # extract rank-and-file stats, resolve the weapon's Combat profile and
    # the target's armour, compile the weapon's rules, and walk one
    # attack. TODO(#46): rank-and-file profile only — a champion fighting
    # at a different WS is a separate attack batch needing unit composition.
    weapon = striker.in_hand()
    profile = weapon.combat_profile
    if profile is None:
        raise ValueError(f"{weapon.name} has no Combat profile; it cannot fight")
    striker_unit, target_unit = striker.unit, target.unit
    weapon_skill = striker_unit.profiles[0][Characteristic.WEAPON_SKILL]
    target_weapon_skill = target_unit.profiles[0][Characteristic.WEAPON_SKILL]
    attacks_per_model = striker_unit.profiles[0][Characteristic.ATTACKS]
    toughness = target_unit.profiles[0][Characteristic.TOUGHNESS]
    if weapon_skill is None:
        raise ValueError(f"{striker_unit.name} has no Weapon Skill; it cannot fight")
    if target_weapon_skill is None:
        raise ValueError(f"{target_unit.name} has no Weapon Skill; its To Hit is undefined")
    if attacks_per_model is None:
        raise ValueError(f"{striker_unit.name} has no Attacks; it cannot fight")
    if toughness is None:
        raise ValueError(f"{target_unit.name} has no Toughness; it cannot be wounded")

    wielder_strength = striker_unit.profiles[0][Characteristic.STRENGTH]
    if profile.strength.is_relative and wielder_strength is None:
        raise ValueError(
            f"{weapon.name} strikes at the wielder's Strength, but {striker_unit.name} has none"
        )
    strength = profile.strength.resolve(wielder_strength or 0)

    armour_value = defender_armour(target.loadout.armour)
    notes: list[str] = []
    # This striker's engagement conditions gate its rules, exactly as a
    # volley's do: a weapon rule whose condition the facts answer is
    # factored (True) or honoured as a no-op (False), one they leave
    # unknown stays noted. The combat chapter's rules in force
    # (phase_rules) apply to every strike, gated by the same facts.
    modifiers, unfactored = compile_rules(
        profile.special_rules, striker.loadout.weapon_rules, conditions
    )
    # A supporting-rank weapon rule (Fight in Extra Rank) is factored into the
    # attack count, not the dice walk, so the walk leaves it unfactored — claim
    # it out, the way shooting claims Volley Fire off a volley.
    supporting_factored = striker.supporting_ranks().factored
    unfactored = [rule for rule in unfactored if rule not in supporting_factored]
    notes.extend(f"weapon rule not factored: {rule} ({weapon.name})" for rule in unfactored)
    phase_modifiers, phase_unfactored = compile_rules(sorted(phase_rules), phase_rules, conditions)
    modifiers.extend(phase_modifiers)
    notes.extend(f"core rule not factored: {name}" for name in phase_unfactored)
    if weapon.notes is not None:
        notes.append(f"weapon notes not factored ({weapon.name}): {weapon.notes}")

    hit = melee_hit_target(weapon_skill, target_weapon_skill, hit_modifier)
    wound = wound_target(strength, toughness)
    save = armour_save_target(armour_value, profile.armour_piercing)
    p_unsaved, p_kill, hit = _per_attack(hit, wound, save, None, modifiers)
    # Wounds accumulate into whole slain models; a profile with no printed
    # Wounds ("-") is treated as a single-Wound model.
    target_wounds = target_unit.profiles[0][Characteristic.WOUNDS] or 1
    logger.debug(
        "%s (WS %d, A %d) vs %s (WS %d, T %d): per-attack unsaved p=%.3f",
        striker_unit.name,
        weapon_skill,
        attacks_per_model,
        target_unit.name,
        target_weapon_skill,
        toughness,
        p_unsaved,
    )
    return _Engagement(
        striker=striker,
        p_unsaved=p_unsaved,
        p_kill=p_kill,
        target_wounds=target_wounds,
        hit_target=hit,
        wound_target=wound,
        save_target=save,
        p_hit=melee_hit_probability(hit),
        p_wound=wound_probability(wound),
        notes=tuple(notes),
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
    side's first (rank-and-file) profile; casualties cap at the target's
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
    engagement = _engage(striker, target, hit_modifier=hit_modifier)
    attacks = engagement.attacks(fighters)
    distribution, casualties = wound_and_casualties(
        attacks,
        p_unsaved=engagement.p_unsaved,
        p_kill=engagement.p_kill,
        wounds_per_model=engagement.target_wounds,
        targets=targets,
    )
    return StrikeResult(
        attacks=attacks,
        hit_target=engagement.hit_target,
        wound_target=engagement.wound_target,
        save_target=engagement.save_target,
        ward_target=None,
        p_hit=engagement.p_hit,
        p_wound=engagement.p_wound,
        p_unsaved=engagement.p_unsaved,
        distribution=distribution,
        casualties=casualties,
        notes=(
            # Only the striker throws blows here, so only its fighting-rank
            # rules (Press of Battle) are in the math and claimed; the
            # target's stay noted until it strikes in its turn.
            *_unit_rule_notes(striker.unit, claimed=striker.fighting_ranks().factored),
            *_unit_rule_notes(target.unit),
            *engagement.notes,
        ),
        target_models=targets,
    )


@dataclass(frozen=True)
class FightResult:
    """Outcome of one round of close combat between two units.

    ``losses`` is the *joint* distribution of models removed:
    ``losses[j][k]`` = P(A lost j models and B lost k). The two sides are
    correlated whenever one strikes first — a side that lost heavily strikes
    back with fewer models — so the joint, not the two marginals, is what a
    combat-result margin must be computed from. ``a_casualties`` and
    ``b_casualties`` are its marginals. ``first_striker`` is the
    :class:`Contingent` that struck first by Initiative, or None when equal
    Initiative made the blows simultaneous. ``a_initiative`` and
    ``b_initiative`` are the effective Initiatives that ordering compared —
    reported so a caller prints the value the math used, as the shooting
    result reports its effective To Hit target. ``a_rank_bonus`` and
    ``b_rank_bonus`` are each side's combat-result Rank Bonus, which
    :func:`combat_result` adds to that side's score.
    """

    losses: list[list[float]]  # losses[a_lost][b_lost] = joint probability
    first_striker: Contingent | None
    notes: tuple[str, ...] = ()
    a_initiative: EffectiveCharacteristic = EffectiveCharacteristic(0)
    b_initiative: EffectiveCharacteristic = EffectiveCharacteristic(0)
    a_rank_bonus: int = 0
    b_rank_bonus: int = 0

    @property
    def a_casualties(self) -> list[float]:
        """Marginal distribution of models A lost (index k = P(k removed))."""
        return [sum(row) for row in self.losses]

    @property
    def b_casualties(self) -> list[float]:
        """Marginal distribution of models B lost (index k = P(k removed))."""
        columns = len(self.losses[0]) if self.losses else 0
        return [sum(row[k] for row in self.losses) for k in range(columns)]


def _unit_rule_notes(unit: Unit, claimed: Collection[str] = ()) -> list[str]:
    # The one owner of a unit rule's disposition: noted unless a consumer
    # claimed it (the initiative read claims what it factored, honoured
    # no-ops included). Notes are built once, never parsed or matched. A
    # rule printed on the datasheet is owned by the unit; a rule the troop
    # type confers (Press of Battle, ...) is owned by the troop type.
    troop_type = unit.troop_type_profile
    owned = [(printed, unit.name) for printed in unit.special_rules]
    if troop_type is not None:
        owned += [(printed, troop_type.name) for printed in troop_type.special_rules]
    return [
        f"special rule not factored: {printed} ({owner})"
        for printed, owner in owned
        if printed not in claimed
    ]


def _combat_conditions(first_round: bool | None, side: Contingent) -> dict[Condition, bool | None]:
    # One fact per Condition member for one side of the combat; None =
    # unknown. Exhaustive like the shooting producer: a new member fails
    # the type check until it is answered here. ``first_round`` is the
    # combat's, a relational fact; the rest read the side's own state.
    def fact(condition: Condition) -> bool | None:
        match condition:
            case Condition.MOVED:
                # A charge is a move, and the Movement folds it in: moved is
                # true for a charge as for any other move this turn.
                return side.movement.moved
            case Condition.CHARGED:
                return side.movement.charge is not None
            case Condition.AT_LONG_RANGE:
                return False  # no shot is taken in close combat
            case Condition.FIRST_ROUND_OF_COMBAT:
                return first_round
            case unanswered:
                assert_never(unanswered)

    return {condition: fact(condition) for condition in Condition}


def effective_initiative(
    contingent: Contingent,
    charge_bonus: int = 0,
    conditions: Mapping[Condition, bool | None] | None = None,
) -> EffectiveCharacteristic:
    """The Initiative a contingent strikes at, all printed modifiers included.

    The striking-order assembler, and the one home of the Initiative
    ceiling: the rank-and-file Initiative, modified by the loadout's
    rule-granted characteristic modifiers under the evaluated
    ``conditions``, plus the ``charge_bonus`` the charge already
    arc-capped (:attr:`~avelorn.tow.contingent.Charge.initiative_bonus`),
    the total capped at 10 (the-combat-phase/charging-units). A profile
    with no printed Initiative counts as 0.

    The charge reaches here once, and only as a number: its facts (that
    the charger moved) travel in ``conditions``, its Initiative
    contribution as ``charge_bonus`` — the :class:`Charge` object is not
    passed, so it cannot arrive twice.

    Returns:
        The Initiative that decides striking order in :func:`fight`,
        with the rule names factored into it and those left unfactored —
        the caller reports the latter.
    """
    base = contingent.unit.profiles[0][Characteristic.INITIATIVE] or 0
    modified = effective_characteristic(
        base, Characteristic.INITIATIVE, contingent.loadout.rules, conditions
    )
    return replace(modified, value=min(modified.value + charge_bonus, 10))


def _prior_loss_pmf(pmf: Sequence[float] | None, models: int, name: str) -> Sequence[float]:
    # A side's pre-combat loss distribution: pmf[k] = P(k models lost before
    # any blows are struck. None means none were lost — certainty at zero. A
    # side cannot lose more models than it fields, and the mass must be a
    # distribution.
    if pmf is None:
        return (1.0,)
    if len(pmf) > models + 1:
        raise ValueError(f"{name} covers more losses ({len(pmf) - 1}) than models ({models})")
    if any(p < 0 for p in pmf):
        raise ValueError(f"{name} has a negative probability")
    if not isclose(sum(pmf), 1.0):
        raise ValueError(f"{name} must sum to 1, got {sum(pmf)}")
    return pmf


def fight(
    a: Contingent,
    b: Contingent,
    *,
    a_prior_losses: Sequence[float] | None = None,
    b_prior_losses: Sequence[float] | None = None,
    first_round: bool | None = None,
    phase_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
) -> FightResult:
    """Resolve one round of close combat between two single-profile units.

    Each side fights with the weapon it has in hand (``a.in_hand()`` /
    ``b.in_hand()``), the one it was armed with through
    :meth:`~avelorn.tow.contingent.Contingent.wielding` — a per-side choice,
    since a unit may carry several (a hand weapon and a great weapon) and
    picks one to swing.

    Striking order is by rank-and-file Initiative (highest first): the
    higher-Initiative side strikes at full strength, its casualties are
    removed, then the lower-Initiative side strikes back **with its
    survivors** — so the loser of that exchange swings with fewer models
    (the-combat-phase: who-strikes-first, fight-on). Equal Initiative
    strikes simultaneously, with no such reduction (simultaneous-combat).

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
    casualties, so pre-combat losses never inflate the combat result.

    Rule-granted characteristic modifiers on the unit (Elven Reflexes)
    apply to the striking order through the loadout of a contingent
    fielded with deploy(), gated on the side's facts; one left
    unevaluated stays noted. Deferred and noted, not modelled here:
    Always Strikes First/Last and the Initiative modifiers granted by
    weapons (a Thrusting Spear's bonus when charged) — surfaced in the
    result's notes; the supporting attacks Fight in Extra Rank / Martial
    Prowess grant the rank behind, split-profile champions (#46), and
    multi-unit combats. Each side fights with its fighting rank only — the
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
    a_lost_before = _prior_loss_pmf(a_prior_losses, a.models, "a_prior_losses")
    b_lost_before = _prior_loss_pmf(b_prior_losses, b.models, "b_prior_losses")
    # Each side's engagement conditions, evaluated once: the same facts
    # gate its strike's dice walk (weapon and chapter rules) and its
    # striking-order Initiative — no fact is computed for one and denied
    # the other.
    a_conditions = _combat_conditions(first_round, a)
    b_conditions = _combat_conditions(first_round, b)
    a_strikes = _engage(a, b, hit_modifier=0, conditions=a_conditions, phase_rules=phase_rules)
    b_strikes = _engage(b, a, hit_modifier=0, conditions=b_conditions, phase_rules=phase_rules)
    a_bonus = 0 if a.movement.charge is None else a.movement.charge.initiative_bonus
    b_bonus = 0 if b.movement.charge is None else b.movement.charge.initiative_bonus
    a_initiative = effective_initiative(a, a_bonus, a_conditions)
    b_initiative = effective_initiative(b, b_bonus, b_conditions)
    a_first = _strikes_first(a_initiative.value, b_initiative.value)

    # Each side may enter already thinned by pre-combat casualties (a Stand &
    # Shoot volley, say); the two are independent, so the round is the
    # fixed-count joint mixed over the product of the loss distributions.
    losses = [[0.0] * (b.models + 1) for _ in range(a.models + 1)]
    for pre_a, p_a in enumerate(a_lost_before):
        for pre_b, p_b in enumerate(b_lost_before):
            weight = p_a * p_b
            if weight == 0.0:
                continue
            joint = _round_joint(a_strikes, a.models - pre_a, b_strikes, b.models - pre_b, a_first)
            for a_lost, row in enumerate(joint):
                for b_lost, mass in enumerate(row):
                    losses[a_lost][b_lost] += weight * mass

    first_striker = None if a_first is None else (a if a_first else b)
    # A rule factored into the striking order or the fighting-rank depth is
    # in the math — claimed, so never noted; both sides strike, so each
    # claims its own. A mirror match dedups the identical remainder.
    notes = tuple(
        dict.fromkeys(
            [
                *_unit_rule_notes(
                    a.unit, claimed={*a_initiative.factored, *a.fighting_ranks().factored}
                ),
                *_unit_rule_notes(
                    b.unit, claimed={*b_initiative.factored, *b.fighting_ranks().factored}
                ),
                *a_strikes.notes,
                *b_strikes.notes,
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
    )


def _fell(engagement: _Engagement, fighters: int, *, targets: int) -> list[float]:
    # Casualties inflicted on the target by ``fighters`` models striking.
    _, casualties = wound_and_casualties(
        engagement.attacks(fighters),
        p_unsaved=engagement.p_unsaved,
        p_kill=engagement.p_kill,
        wounds_per_model=engagement.target_wounds,
        targets=targets,
    )
    return casualties


def _independent(
    row_strikes: _Engagement, row_fighters: int, col_strikes: _Engagement, col_fighters: int
) -> list[list[float]]:
    # Simultaneous combat: neither side's casualties reduce the other's
    # blows, so the two loss distributions are independent — the joint is
    # their outer product. Each side's losses come from the other's strike.
    row_losses = _fell(col_strikes, col_fighters, targets=row_fighters)
    col_losses = _fell(row_strikes, row_fighters, targets=col_fighters)
    return [[p_row * p_col for p_col in col_losses] for p_row in row_losses]


def _sequenced(
    first_strikes: _Engagement,
    first_fighters: int,
    second_strikes: _Engagement,
    second_fighters: int,
) -> list[list[float]]:
    # The first side strikes at full strength; its casualties thin the second
    # before the survivors strike back, so the second's blows are conditioned
    # on how many of it remain. Returns joint[first_lost][second_lost].
    joint = [[0.0] * (second_fighters + 1) for _ in range(first_fighters + 1)]
    for second_lost, p_second in enumerate(
        _fell(first_strikes, first_fighters, targets=second_fighters)
    ):
        if p_second == 0.0:
            continue
        survivors = second_fighters - second_lost
        for first_lost, p_first in enumerate(
            _fell(second_strikes, survivors, targets=first_fighters)
        ):
            joint[first_lost][second_lost] += p_second * p_first
    return joint


def _transpose(joint: list[list[float]]) -> list[list[float]]:
    # Swap axes: [second_lost][first_lost] -> [first_lost][second_lost].
    return [list(row) for row in zip(*joint, strict=True)]


def _strikes_first(initiative_a: int, initiative_b: int) -> bool | None:
    # Who strikes first by Initiative: True if A does, False if B, None when
    # equal Initiative makes the blows simultaneous.
    if initiative_a == initiative_b:
        return None
    return initiative_a > initiative_b


def _round_joint(
    a_strikes: _Engagement,
    a_models: int,
    b_strikes: _Engagement,
    b_models: int,
    a_first: bool | None,
) -> list[list[float]]:
    # One round's joint casualty distribution at fixed model counts, oriented
    # to (a, b). Equal Initiative (a_first is None) strikes simultaneously —
    # independent losses; otherwise the first striker thins the other before
    # it swings back, and the sequenced joint is oriented back to (a, b).
    if a_first is None:
        return _independent(a_strikes, a_models, b_strikes, b_models)
    if a_first:
        return _sequenced(a_strikes, a_models, b_strikes, b_models)
    return _transpose(_sequenced(b_strikes, b_models, a_strikes, a_models))


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
    inflicted plus its Rank Bonus; the remaining components are listed in
    ``notes`` (#28). For 1-Wound models wounds inflicted equal models
    removed; the wound-count for multi-Wound models is not modelled. The
    signed ``margin`` is what the Break test adds to the loser's roll.
    """

    p_a_wins: float
    p_draw: float
    p_b_wins: float
    margin: dict[int, float]
    notes: tuple[str, ...] = ()


def combat_result(result: FightResult) -> CombatResult:
    """Score a fought round by unsaved wounds inflicted and name the winner.

    Composes on a :class:`FightResult`'s joint loss distribution: A's score
    is how many models (= wounds, for 1-Wound units) B lost plus A's Rank
    Bonus, B's the reverse. The rank bonuses are fixed per side, so they
    shift every lead by the same constant. Because the two sides are
    correlated under Initiative order, the win/draw/win split and the
    signed margin come from the joint, not from differencing the marginals.

    Returns:
        The exact win/draw/loss probabilities and signed margin distribution.
    """
    margin: dict[int, float] = {}
    p_a_wins = p_draw = p_b_wins = 0.0
    rank_delta = result.a_rank_bonus - result.b_rank_bonus
    for a_lost, row in enumerate(result.losses):
        for b_lost, mass in enumerate(row):
            if mass == 0.0:
                continue
            lead = (b_lost - a_lost) + rank_delta  # A scores B's losses + ranks; B the reverse
            margin[lead] = margin.get(lead, 0.0) + mass
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

    p_gives_ground: float
    p_falls_back: float
    p_breaks: float


@dataclass(frozen=True)
class BreakResult:
    """Both sides' Break-test outcomes for one round of close combat.

    A round has at most one loser, so ``a`` and ``b`` are mutually
    exclusive — each is non-zero only across the outcomes where that side
    lost. ``p_draw`` is the chance of a drawn combat, in which neither side
    tests. The two sides' six outcome probabilities and ``p_draw`` sum to 1.
    """

    a: SideBreak
    b: SideBreak
    p_draw: float


def break_test(result: CombatResult, unit_a: Unit, unit_b: Unit) -> BreakResult:
    """Resolve the Break test for a scored combat round, for each side.

    Only the losing side rolls: 2D6, add the winner's margin, compare to
    its Leadership (highest value in the unit). A natural roll above
    Leadership Breaks and flees; a natural roll within it but a modified
    roll above Falls Back in Good Order; a modified roll within it — or a
    natural double 1 — Gives Ground (the-combat-phase/break-test). The
    winner takes no Break test (its follow-up and pursuit choices are not
    modelled here), and a drawn combat tests neither side.

    Composes on the signed margin distribution: ``unit_a`` is the
    positive-margin side, matching :func:`fight`'s ``a``.

    Returns:
        Each side's Break-test outcomes for the rounds it loses, plus the
        drawn-combat probability.
    """
    a_leadership = unit_a.highest(Characteristic.LEADERSHIP) or 0
    b_leadership = unit_b.highest(Characteristic.LEADERSHIP) or 0
    logger.debug("break test: Ld %d (a) vs Ld %d (b)", a_leadership, b_leadership)
    return BreakResult(
        a=_side_break(
            result.margin, a_leadership, deficit=lambda lead: -lead if lead < 0 else None
        ),
        b=_side_break(
            result.margin, b_leadership, deficit=lambda lead: lead if lead > 0 else None
        ),
        p_draw=sum(mass for lead, mass in result.margin.items() if lead == 0),
    )


def _side_break(
    margin: Mapping[int, float], leadership: int, *, deficit: Callable[[int], int | None]
) -> SideBreak:
    # Aggregate one side's Break-test outcomes over the rounds it loses.
    # ``deficit(lead)`` is this side's losing margin at signed lead ``lead``,
    # or None when it did not lose (it won, or the combat was drawn) and so
    # takes no test.
    breaks = falls_back = gives_ground = 0.0
    for lead, mass in margin.items():
        loss = deficit(lead)
        if loss is None:
            continue
        p_break, p_fall, p_give = _break_outcomes(leadership, loss)
        breaks += mass * p_break
        falls_back += mass * p_fall
        gives_ground += mass * p_give
    return SideBreak(p_gives_ground=gives_ground, p_falls_back=falls_back, p_breaks=breaks)


def _break_outcomes(leadership: int, margin: int) -> tuple[float, float, float]:
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
    return breaks / 36, falls_back / 36, gives_ground / 36


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

    def break_test(self, scored: CombatResult, a: Unit, b: Unit) -> BreakResult:
        """The Break test for a scored round, for each side.

        Returns:
            Each side's break outcome distribution.
        """
        return break_test(scored, a, b)
