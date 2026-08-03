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
from itertools import product
from math import isclose
from typing import ClassVar, overload

from avelorn.core.dice import expected_value
from avelorn.core.game import Phase
from avelorn.tow.contingent import Contingent
from avelorn.tow.engine.armour import defender_armour
from avelorn.tow.engine.attack import (
    ArmourSave,
    AttackProfile,
    Modifier,
    Outcome,
    Reroll,
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
    AttackFacts,
    ChargeEvent,
    CombatFacts,
    EffectiveRerolls,
    EffectiveValue,
    GateContext,
    MovementFacts,
    ShootingFacts,
    compile_rules,
    effective_armour_value,
    effective_characteristic,
    effective_combat_result_bonus,
    effective_rerolls,
    factored_notes,
    forced_outcome,
)
from avelorn.tow.phases.movement import Engagement
from avelorn.tow.schema.psychology import BreakOutcome
from avelorn.tow.schema.rule import AttackKind, Decision, Rule
from avelorn.tow.schema.stage import Side
from avelorn.tow.schema.unit import Characteristic

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
    rerolls: Sequence[Reroll] = (),
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
        rerolls,
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
    weapon_skill: EffectiveValue
    target_armour: EffectiveValue
    rerolls: EffectiveRerolls
    # The target's rules read from its seat of this walk — its own save
    # re-rolls, its enemy-subject maluses on the striker's dice.
    target_rerolls: EffectiveRerolls
    # Each side's unit rules the dice walk factored, claimed by the callers
    # so a rule in the math is never also reported as not factored — and,
    # apart, those the *other* seat of the walk owns. A caller resolving both
    # seats claims those too; a one-sided one reports them, since nothing in
    # its single walk consumed them.
    walk_factored: frozenset[str]
    walk_inapplicable: frozenset[str]
    target_walk_factored: frozenset[str]
    target_walk_inapplicable: frozenset[str]
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
    conditions: "GateContext | None" = None,
    target_conditions: "GateContext | None" = None,
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
    # The defender's own rules may better its save (Parry's +1 with a hand
    # weapon and shield in use), gated on its equipment and engagement facts;
    # a lower armour value is a better save. Nothing to improve unarmoured.
    if armour_value is None:
        target_armour = EffectiveValue(0)
    else:
        target_armour = effective_armour_value(
            armour_value,
            target.loadout.rules,
            target_conditions,
        )
        armour_value = target_armour.value
    notes: list[str] = []
    # This striker's engagement conditions gate its rules, exactly as a
    # volley's do: a weapon rule whose condition the facts answer is
    # factored (True) or honoured as a no-op (False), one they leave
    # unknown stays noted. The combat chapter's rules in force
    # (phase_rules) apply to every strike, gated by the same facts.
    weapon_compiled = compile_rules(
        profile.special_rules, striker.loadout.weapon_rules, conditions
    )
    modifiers = list(weapon_compiled.modifiers)
    # The striker's own unit rules move the same dice — Gromril Weapons gives
    # its hand weapon an Armour Piercing characteristic of -1 — gated on the
    # weapon in hand, exactly as a volley reads Arrows of Isha. What the walk
    # factors is claimed, so the "special rule not factored" notes stay true;
    # what it cannot (Strike First's Initiative set, Ithilmar Weapons'
    # re-roll) belongs to another seam and is claimed by that one.
    unit_index = {rule.name: rule for rule in striker.loadout.rules}
    unit_compiled = compile_rules(
        list(unit_index), unit_index, conditions, grants=striker.loadout.granted_rules
    )
    modifiers.extend(unit_compiled.modifiers)
    # The target's own rules reach the same walk from the other seat: an
    # enemy-subject rule of the target's ("-1 to hit this unit") lands on
    # this striker's Roll to Hit, gated on the target's own facts — the
    # incoming attack among them. Rules whose quantities belong to the
    # striker's seat compile to nothing here (inapplicable, kept apart so a
    # one-sided strike still reports them); those belonging to another seam
    # (Parry's armour value, claimed by the armour fold) are claimed there.
    target_index = {rule.name: rule for rule in target.loadout.rules}
    target_compiled = compile_rules(
        list(target_index),
        target_index,
        target_conditions,
        seat=Side.TARGET,
        grants=target.loadout.granted_rules,
    )
    modifiers.extend(target_compiled.modifiers)
    # Each side's rules may re-roll the walk's dice, from its own seat: the
    # striker its own To Hit (Ithilmar Weapons' natural 1s) or, with an
    # enemy-subject grant, the target's save (Daith's Reaper's forced
    # re-roll of its passes); the target its own save (Gromril Armour's
    # natural 1s while defending). The striker's grants come from its unit
    # rules and from the rules of the profile in use — a magic weapon's
    # rule is scoped by wielding it — each gated on that side's conditions,
    # exactly as the armour fold gates the defender's save.
    in_use = [
        striker.loadout.weapon_rules[name]
        for name in profile.special_rules
        if name in striker.loadout.weapon_rules
    ]
    # Compiled per source, not as one pool: unit-rule names claim unit-rule
    # notes and weapon-rule names claim weapon-rule notes, so a printed name
    # shared across the two namespaces cannot claim the other's note.
    rerolls = effective_rerolls(striker.loadout.rules, conditions, seat=Side.ATTACKER)
    weapon_rerolls = effective_rerolls(in_use, conditions, seat=Side.ATTACKER)
    target_rerolls = effective_rerolls(target.loadout.rules, target_conditions, seat=Side.TARGET)
    # A weapon rule the walk cannot factor may still be consumed by another
    # seam: the supporting-rank query (Fight in Extra Rank, folded into the
    # attack count), the striking-order Initiative read (a great weapon's
    # Strike Last, which sets Initiative), or the re-roll seam (Daith's
    # Reaper). Claim all three out of the walk's unfactored notes, the way
    # shooting claims Volley Fire off a volley. The weapon in hand is only
    # ever compiled from its wielder's seat — no second compile covers a
    # weapon rule aimed at the other one — so an inapplicable weapon rule is
    # reported here, not claimed.
    claimed = {
        *striker.supporting_ranks().factored,
        *effective_initiative(striker, conditions=conditions).factored,
        *weapon_rerolls.factored,
    }
    unfactored = [
        rule
        for rule in (*weapon_compiled.unfactored, *weapon_compiled.inapplicable)
        if rule not in claimed
    ]
    notes.extend(f"weapon rule not factored: {rule} ({weapon.name})" for rule in unfactored)
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
    # gated on that side's own engagement conditions.
    striker_ws = effective_weapon_skill(striker, conditions)
    target_ws = effective_weapon_skill(target, target_conditions)
    hit = melee_hit_target(striker_ws.value, target_ws.value, hit_modifier)
    wound = wound_target(strength, toughness)
    save = armour_save_target(armour_value, profile.armour_piercing)
    p_unsaved, p_kill, hit = _per_attack(
        hit,
        wound,
        save,
        None,
        modifiers,
        rerolls=(*rerolls.rerolls, *weapon_rerolls.rerolls, *target_rerolls.rerolls),
    )
    # Wounds accumulate into whole slain models; a profile with no printed
    # Wounds ("-") is treated as a single-Wound model.
    target_wounds = target_unit.profiles[0][Characteristic.WOUNDS] or 1
    logger.debug(
        "%s (WS %d, A %d) vs %s (WS %d, T %d): per-attack unsaved p=%.3f",
        striker_unit.name,
        striker_ws.value,
        attacks_per_model,
        target_unit.name,
        target_ws.value,
        toughness,
        p_unsaved,
    )
    return _Engagement(
        striker=striker,
        weapon_skill=striker_ws,
        target_armour=target_armour,
        rerolls=rerolls,
        target_rerolls=target_rerolls,
        walk_factored=frozenset(unit_compiled.factored),
        walk_inapplicable=frozenset(unit_compiled.inapplicable),
        target_walk_factored=frozenset(target_compiled.factored),
        target_walk_inapplicable=frozenset(target_compiled.inapplicable),
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
    # A single strike is close combat, so combat is present — but the round it
    # falls in, and how the sides outnumber, are not known here, so first-round
    # and outnumbering rules stay unfactored and noted. The target is the target
    # of this close-combat attack (magical if the striker's weapon in hand is),
    # the fact Parry (combat present) and Lion Cloak (an incoming attack) read
    # for its save; the striker throws the only blows, so it is not itself a
    # target here. Each side carries its own equipment in use, so Parry reads the
    # target's shield and Ithilmar Weapons the striker's hand weapon.
    in_hand = striker.in_hand().combat_profile
    striker_conditions = GateContext(
        combat=CombatFacts(),
        wielding=striker.weapon_facts,
        worn=striker.armour_facts,
    )
    target_conditions = GateContext(
        combat=CombatFacts(),
        wielding=target.weapon_facts,
        worn=target.armour_facts,
        target_of=AttackFacts(
            kind=AttackKind.CLOSE_COMBAT,
            magical=in_hand is not None and "Magical Attacks" in in_hand.special_rules,
        ),
    )
    engagement = _engage(
        striker,
        target,
        hit_modifier=hit_modifier,
        conditions=striker_conditions,
        target_conditions=target_conditions,
    )
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
                    *engagement.weapon_skill.factored,
                    *engagement.rerolls.factored,
                    *engagement.walk_factored,
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
                    *engagement.target_armour.factored,
                    *engagement.target_rerolls.factored,
                    *engagement.target_walk_factored,
                },
            ),
            *engagement.notes,
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

    losses: list[list[float]]  # losses[a_lost][b_lost] = joint probability
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
    wound_margin: dict[int, float] = field(default_factory=dict)

    @property
    def a_casualties(self) -> list[float]:
        """Marginal distribution of models A lost in the melee (index k = P(k removed))."""
        return [sum(row) for row in self.losses]

    @property
    def b_casualties(self) -> list[float]:
        """Marginal distribution of models B lost in the melee (index k = P(k removed))."""
        columns = len(self.losses[0]) if self.losses else 0
        return [sum(row[k] for row in self.losses) for k in range(columns)]

    @property
    def scoring_wounds(self) -> dict[int, float]:
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
        derived: dict[int, float] = {}
        for a_lost, row in enumerate(self.losses):
            for b_lost, mass in enumerate(row):
                if mass:
                    diff = b_lost - a_lost
                    derived[diff] = derived.get(diff, 0.0) + mass
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
        worn=side.armour_facts,
        target_of=AttackFacts(
            kind=AttackKind.CLOSE_COMBAT,
            magical=foe_profile is not None and "Magical Attacks" in foe_profile.special_rules,
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
    base = contingent.unit.profiles[0][Characteristic.INITIATIVE] or 0
    rules = [*contingent.loadout.rules, *contingent.in_hand_rules()]
    modified = effective_characteristic(base, Characteristic.INITIATIVE, rules, conditions)
    return replace(modified, value=min(modified.value + charge_bonus, 10))


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
    base = contingent.unit.profiles[0][Characteristic.WEAPON_SKILL] or 0
    return effective_characteristic(
        base, Characteristic.WEAPON_SKILL, contingent.loadout.rules, conditions
    )


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
    a_lost_before = _prior_loss_pmf(a_prior_losses, a.models, "a_prior_losses")
    b_lost_before = _prior_loss_pmf(b_prior_losses, b.models, "b_prior_losses")
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
    a_bonus = 0 if a.movement.charge is None else a.movement.charge.initiative_bonus
    b_bonus = 0 if b.movement.charge is None else b.movement.charge.initiative_bonus
    a_initiative = effective_initiative(a, a_bonus, a_conditions)
    b_initiative = effective_initiative(b, b_bonus, b_conditions)
    a_first = _strikes_first(a_initiative.value, b_initiative.value)
    # Each side's rule-granted combat-result points, summed under its facts
    # (Massed Infantry's +1 when it outnumbers): folded here, added to the
    # score in combat_result, and claimed out of the notes below.
    a_combat_result = effective_combat_result_bonus(a.loadout.rules, a_conditions)
    b_combat_result = effective_combat_result_bonus(b.loadout.rules, b_conditions)

    # Each side may enter already thinned by pre-combat casualties (a Stand &
    # Shoot volley, say); the two are independent, so the round is the
    # fixed-count joint mixed over the product of the loss distributions.
    # ``losses`` keeps the melee joint (for the casualty marginals);
    # ``wound_margin`` accrues the combat-result wound difference, which counts
    # a Stand & Shoot's wounds too: a side's pre-melee losses were the *other*
    # side's volley, so they credit that other side (rulebook: unsaved wounds
    # inflicted, including by a Stand & Shoot this turn). The credit is a
    # per-branch constant (pre_a, pre_b) shifting the melee difference, so the
    # thinning and the credit stay correlated — the same volley that felled
    # ``pre_a`` of A both lightens A's return blows and scores for B. (Counts
    # models removed, = wounds for the 1-Wound models the engine fields; a
    # multi-Wound Stand & Shoot would credit wounds, not casualties.)
    losses = [[0.0] * (b.models + 1) for _ in range(a.models + 1)]
    wound_margin: dict[int, float] = {}
    for pre_a, p_a in enumerate(a_lost_before):
        for pre_b, p_b in enumerate(b_lost_before):
            weight = p_a * p_b
            if weight == 0.0:
                continue
            joint = _round_joint(a_strikes, a.models - pre_a, b_strikes, b.models - pre_b, a_first)
            for a_lost, row in enumerate(joint):
                for b_lost, mass in enumerate(row):
                    contribution = weight * mass
                    losses[a_lost][b_lost] += contribution
                    diff = (b_lost + pre_b) - (a_lost + pre_a)
                    wound_margin[diff] = wound_margin.get(diff, 0.0) + contribution

    first_striker = None if a_first is None else (a if a_first else b)
    # A rule factored into the striking order, the fighting-rank depth, the
    # effective Attacks, or the effective Weapon Skill is in the math — claimed,
    # so never noted; both sides strike, so each claims its own. A mirror match
    # dedups the identical remainder. Both seats of both walks are resolved
    # here, so each side also claims what the seat it did not compile from
    # skipped as inapplicable: whatever one seat is not the business of, the
    # other seat's compile has.
    notes = tuple(
        dict.fromkeys(
            [
                *_unit_rule_notes(
                    a,
                    claimed={
                        *a_initiative.factored,
                        *a.fighting_ranks().factored,
                        *a.effective_attacks().factored,
                        *a_strikes.weapon_skill.factored,
                        *a_strikes.rerolls.factored,
                        *a_strikes.rerolls.inapplicable,
                        *a_strikes.walk_factored,
                        *a_strikes.walk_inapplicable,
                        *a_combat_result.factored,
                        # a's defensive rules are read while it is b's target
                        *b_strikes.target_armour.factored,
                        *b_strikes.target_rerolls.factored,
                        *b_strikes.target_rerolls.inapplicable,
                        *b_strikes.target_walk_factored,
                        *b_strikes.target_walk_inapplicable,
                    },
                ),
                *_unit_rule_notes(
                    b,
                    claimed={
                        *b_initiative.factored,
                        *b.fighting_ranks().factored,
                        *b.effective_attacks().factored,
                        *b_strikes.weapon_skill.factored,
                        *b_strikes.rerolls.factored,
                        *b_strikes.rerolls.inapplicable,
                        *b_strikes.walk_factored,
                        *b_strikes.walk_inapplicable,
                        *b_combat_result.factored,
                        *a_strikes.target_armour.factored,
                        *a_strikes.target_rerolls.factored,
                        *a_strikes.target_rerolls.inapplicable,
                        *a_strikes.target_walk_factored,
                        *a_strikes.target_walk_inapplicable,
                    },
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
        a_unit_strength=a.unit_strength(),
        b_unit_strength=b.unit_strength(),
        a_combat_result_bonus=a_combat_result.value,
        b_combat_result_bonus=b_combat_result.value,
        wound_margin=wound_margin,
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
    inflicted plus its Rank Bonus and any rule-granted combat-result points
    (Massed Infantry's outnumbering +1); the components still unmodelled are
    listed in ``notes`` (#28). For 1-Wound models wounds inflicted equal
    models removed; the wound-count for multi-Wound models is not modelled.
    The signed ``margin`` is what the Break test adds to the loser's roll.
    """

    p_a_wins: float
    p_draw: float
    p_b_wins: float
    margin: dict[int, float]
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
    margin: dict[int, float] = {}
    p_a_wins = p_draw = p_b_wins = 0.0
    # A's fixed edge over B: Rank Bonus plus the rule-granted combat-result
    # points (Massed Infantry, ...), each a signed per-side constant that
    # shifts every lead alike. The wound difference (melee + Stand & Shoot)
    # carries the rest.
    static_delta = (result.a_rank_bonus - result.b_rank_bonus) + (
        result.a_combat_result_bonus - result.b_combat_result_bonus
    )
    for wound_diff, mass in result.scoring_wounds.items():
        if mass == 0.0:
            continue
        lead = wound_diff + static_delta
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
    ``notes`` surface what a rule that fixed an outcome (Stubborn) did and the
    parts of it the current scope does not model.
    """

    a: SideBreak
    b: SideBreak
    p_draw: float
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
    logger.debug(
        "break test: Ld %d (a, forced=%s) vs Ld %d (b, forced=%s)",
        a_leadership,
        a_forced,
        b_leadership,
        b_forced,
    )
    # Relay the fixed-outcome rule's own authored notes (its unmodelled scope),
    # the same generic relay every seam shares — never engine-composed prose.
    notes = tuple(
        note
        for side, rule in ((a, a_rule), (b, b_rule))
        if rule is not None
        for note in factored_notes(
            side.loadout.rules, {rule.name}, side.unit.name, side.loadout.granted_rules
        )
    )
    return BreakResult(
        a=_side_break(
            result.margin,
            a_leadership,
            deficit=lambda lead: -lead if lead < 0 else None,
            forced=a_forced,
        ),
        b=_side_break(
            result.margin,
            b_leadership,
            deficit=lambda lead: lead if lead > 0 else None,
            forced=b_forced,
        ),
        p_draw=sum(mass for lead, mass in result.margin.items() if lead == 0),
        notes=notes,
    )


def _side_break(
    margin: Mapping[int, float],
    leadership: int,
    *,
    deficit: Callable[[int], int | None],
    forced: BreakOutcome | None = None,
) -> SideBreak:
    # Aggregate one side's Break-test outcomes over the rounds it loses.
    # ``deficit(lead)`` is this side's losing margin at signed lead ``lead``,
    # or None when it did not lose (it won, or the combat was drawn) and so
    # takes no test. ``forced`` fixes the outcome (Stubborn): the whole losing
    # mass goes to that result rather than the rolled split.
    breaks = falls_back = gives_ground = 0.0
    for lead, mass in margin.items():
        loss = deficit(lead)
        if loss is None:
            continue
        if forced is BreakOutcome.BREAKS:
            breaks += mass
        elif forced is BreakOutcome.FALLS_BACK:
            falls_back += mass
        elif forced is BreakOutcome.GIVES_GROUND:
            gives_ground += mass
        else:
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

    def break_test(self, scored: CombatResult, a: Contingent, b: Contingent) -> BreakResult:
        """The Break test for a scored round, for each side.

        Each contingent supplies its Leadership and its resolved rules (a
        fixed-outcome rule like Stubborn is read here).

        Returns:
            Each side's break outcome distribution, plus any fixed-outcome notes.
        """
        return break_test(scored, a, b)
