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
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isclose

from avelorn.core.dice import expected_value
from avelorn.core.registry import Registry
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
from avelorn.tow.schema.unit import Characteristic, Complement, Unit
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
    p_unsaved, p_kill, hit = _per_attack(hit, wound, save, ward_target, transforms)
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


def _per_attack(
    hit: int,
    wound: int | None,
    save: int | None,
    ward: int | None,
    transforms: Sequence[Transform],
) -> tuple[float, float, int]:
    # Walk one melee attack's dice exactly, returning its per-attack
    # unsaved-wound and instant-kill probabilities and the effective To Hit
    # target after transforms — the counts that depend only on the matchup,
    # not on how many models are swinging.
    resolution = resolve_attack(
        AttackProfile(
            hit_target=hit,
            wound_target=_roll_target(wound),
            save_target=_roll_target(save),
            ward_target=_roll_target(ward),
        ),
        transforms,
        hit_roll=HitRoll.MELEE,
    )
    effective = resolution.hit_target if isinstance(resolution.hit_target, int) else hit
    return float(resolution.p_unsaved), float(resolution.p_of(Outcome.INSTANT_KILL)), effective


@dataclass(frozen=True)
class _Engagement:
    """One side's per-attack resolution against a specific foe.

    The matchup-dependent, fighter-count-independent half of a melee
    strike: the per-attack probabilities and reported targets, plus the
    Attacks each model makes and the defender's Wounds. Given a number of
    fighters, :func:`wound_and_casualties` turns it into a casualty
    distribution — so the dice walk runs once even when the same side
    strikes with several fighter counts (a return strike whose numbers
    depend on casualties already taken).
    """

    p_unsaved: float
    p_kill: float
    attacks_per_model: int
    defender_wounds: int
    hit_target: int
    wound_target: int | None
    save_target: int | None
    p_hit: float
    p_wound: float
    notes: tuple[str, ...]


def _engage(
    attacker: Unit,
    defender: Unit,
    weapon: Weapon,
    *,
    armoury: Registry[Armour],
    rules: Registry[Rule],
    hit_modifier: int,
) -> _Engagement:
    # The matchup half of a strike, shared by strike_unit and fight:
    # extract rank-and-file stats, resolve the weapon's Combat profile and
    # the defender's armour, compile the weapon's rules, and walk one
    # attack. TODO(#46): rank-and-file profile only — a champion fighting
    # at a different WS is a separate attack batch needing unit composition.
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

    armour_value, notes = defender_armour(defender, armoury)
    for unit in (attacker, defender):
        notes.extend(
            f"special rule not factored: {rule} ({unit.name})" for rule in unit.special_rules
        )
    # Melee engagement conditions (charging, flank/rear, ...) are not
    # modelled yet, so no facts are supplied: a rule needing one stays
    # unfactored and noted.
    transforms, unfactored = compile_rules(profile.special_rules, rules)
    notes.extend(f"weapon rule not factored: {rule} ({weapon.name})" for rule in unfactored)
    if weapon.notes is not None:
        notes.append(f"weapon notes not factored ({weapon.name}): {weapon.notes}")

    hit = melee_hit_target(weapon_skill, target_weapon_skill) - hit_modifier
    wound = wound_target(strength, toughness)
    save = armour_save_target(armour_value, profile.armour_piercing)
    p_unsaved, p_kill, hit = _per_attack(hit, wound, save, None, transforms)
    # Wounds accumulate into whole slain models; a profile with no printed
    # Wounds ("-") is treated as a single-Wound model.
    defender_wounds = defender.profiles[0][Characteristic.WOUNDS] or 1
    logger.debug(
        "%s (WS %d, A %d) vs %s (WS %d, T %d): per-attack unsaved p=%.3f",
        attacker.name,
        weapon_skill,
        attacks_per_model,
        defender.name,
        target_weapon_skill,
        toughness,
        p_unsaved,
    )
    return _Engagement(
        p_unsaved=p_unsaved,
        p_kill=p_kill,
        attacks_per_model=attacks_per_model,
        defender_wounds=defender_wounds,
        hit_target=hit,
        wound_target=wound,
        save_target=save,
        p_hit=melee_hit_probability(hit),
        p_wound=wound_probability(wound),
        notes=tuple(notes),
    )


def strike_unit(
    attacker: Unit,
    defender: Unit,
    fighters: int,
    weapon: Weapon,
    *,
    armoury: Registry[Armour] | None = None,
    rules: Registry[Rule] | None = None,
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
    if fighters < 0:
        raise ValueError("fighters must be >= 0")
    engagement = _engage(
        attacker,
        defender,
        weapon,
        armoury=armoury or Registry[Armour](),
        rules=rules or Registry[Rule](),
        hit_modifier=hit_modifier,
    )
    attacks = fighters * engagement.attacks_per_model
    distribution, casualties = wound_and_casualties(
        attacks,
        p_unsaved=engagement.p_unsaved,
        p_kill=engagement.p_kill,
        wounds_per_model=engagement.defender_wounds,
        targets=defenders,
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
        notes=engagement.notes,
        target_models=defenders,
    )


class ChargeArc(StrEnum):
    """Which arc a charge struck.

    The rulebook caps the charge Initiative bonus per arc (front vs flank
    or rear), but flank and rear diverge elsewhere — the combat-result
    bonuses each grants differ (#28) — so all three are distinguished here.
    """

    FRONT = "front"
    FLANK = "flank"
    REAR = "rear"


@dataclass(frozen=True)
class Charge:
    """A charge move, feeding the charger's Combat-phase Initiative bonus.

    A model that charged gains +1 Initiative per full inch it moved before
    contact — capped at +3 into the enemy's front arc, +4 into its flank or
    rear (the-combat-phase/charging-units). :func:`fight` caps the resulting
    Initiative at 10, as the rule requires. The flank/rear *combat-result*
    bonuses that same arc would grant are a separate, still-deferred
    concern (#28); only the Initiative modifier is read here.
    """

    full_inches: int
    arc: ChargeArc = ChargeArc.FRONT

    def initiative_bonus(self) -> int:
        """The Initiative modifier this charge grants its models.

        Returns:
            +1 per full inch moved, clamped to the arc's cap (+3 into the
            front, +4 into the flank or rear) and never below zero.
        """
        cap = 3 if self.arc is ChargeArc.FRONT else 4
        return min(max(self.full_inches, 0), cap)


@dataclass(frozen=True)
class Contingent:
    """A unit as fielded: its datasheet and the models on the table.

    The datasheet (:class:`~avelorn.tow.schema.unit.Unit`) is a template —
    it carries the *allowed* size, not how many models stand on the table —
    so ``models`` supplies the fielded count. ``charge`` is the charge this
    contingent made this turn, if any; its Initiative bonus decides who
    strikes first in :func:`fight`, and a contingent that did not charge
    (any shooter among them) leaves it None.

    Construct one directly — ``Contingent(unit, models, charge)`` — for an
    arbitrary body on the table: a post-casualty remnant, or an isolated count
    for analysis, neither of which need be a legal army-list size. To field a
    mustered list entry instead, use :meth:`deploy`, which takes a
    :class:`~avelorn.tow.schema.unit.Complement` (list-legal size, chosen
    options) and bakes its loadout into the datasheet the engine reads.

    The weapon in use is *not* carried here: it is a per-action choice, so
    the same contingent shoots with its bow one moment and fights the
    ensuing melee with a hand weapon the next. Each action takes the chosen
    weapon (:func:`fight`, :func:`~avelorn.tow.combat.charge.stand_and_shoot`).

    Today a contingent is a single homogeneous body — one profile (the
    rank-and-file, ``unit.profiles[0]``), as with :func:`strike_unit`. A real
    contingent can be heterogeneous: rank and file plus a champion, plus an
    embedded character, each its own profile, Attacks and weapon. That is
    deliberately not modelled yet (#46); when it is, this grows a notion of
    *parts* and the single-body fields become the one-part case. Callers read
    only ``profiles[0]``, so the assumption stays localized to that migration.
    """

    unit: Unit
    models: int
    charge: Charge | None = None

    @classmethod
    def deploy(cls, complement: Complement, charge: Charge | None = None) -> "Contingent":
        """Field a :class:`~avelorn.tow.schema.unit.Complement` as a contingent.

        The complement's chosen loadout — its equipment and special rules
        after its options' adds and removes — is baked into the datasheet the
        engine reads, so the contingent fights with what was bought, not the
        printed profile. The chosen ``size`` becomes ``models``.

        Args:
            complement: The list entry to field.
            charge: The charge this contingent made this turn, if any.

        Returns:
            The fielded contingent.
        """
        fielded = complement.unit.model_copy(
            update={
                "equipment": complement.equipment,
                "special_rules": complement.special_rules,
            }
        )
        return cls(fielded, complement.size, charge)


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
    Initiative made the blows simultaneous.
    """

    losses: list[list[float]]  # losses[a_lost][b_lost] = joint probability
    first_striker: Contingent | None
    notes: tuple[str, ...] = ()

    @property
    def a_casualties(self) -> list[float]:
        """Marginal distribution of models A lost (index k = P(k removed))."""
        return [sum(row) for row in self.losses]

    @property
    def b_casualties(self) -> list[float]:
        """Marginal distribution of models B lost (index k = P(k removed))."""
        columns = len(self.losses[0]) if self.losses else 0
        return [sum(row[k] for row in self.losses) for k in range(columns)]


def _effective_initiative(contingent: Contingent) -> int:
    # A contingent's Initiative for striking order: its rank-and-file value
    # plus any charge bonus, capped at 10 as the-combat-phase/charging-units
    # requires. A profile with no printed Initiative counts as 0.
    base = contingent.unit.profiles[0][Characteristic.INITIATIVE] or 0
    bonus = contingent.charge.initiative_bonus() if contingent.charge is not None else 0
    return min(base + bonus, 10)


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
    a_weapon: Weapon,
    b_weapon: Weapon,
    a_prior_losses: Sequence[float] | None = None,
    b_prior_losses: Sequence[float] | None = None,
    armoury: Registry[Armour] | None = None,
    rules: Registry[Rule] | None = None,
) -> FightResult:
    """Resolve one round of close combat between two single-profile units.

    ``a_weapon`` and ``b_weapon`` are the Combat weapons each side fights
    with — a per-side choice, since a unit may carry several (a hand weapon
    and a great weapon) and picks one to swing.

    Striking order is by rank-and-file Initiative (highest first): the
    higher-Initiative side strikes at full strength, its casualties are
    removed, then the lower-Initiative side strikes back **with its
    survivors** — so the loser of that exchange swings with fewer models
    (the-combat-phase: who-strikes-first, fight-on). Equal Initiative
    strikes simultaneously, with no such reduction (simultaneous-combat).

    A charging side's ``charge`` adds its Initiative bonus before the
    comparison (the-combat-phase/charging-units); the modified Initiative
    is capped at 10. The two sides are otherwise symmetric; only Initiative
    orders them. Resolution happens in strike order and the joint is
    oriented back to the ``(a, b)`` axes the caller passed.

    ``a_prior_losses`` / ``b_prior_losses`` let a side enter already thinned:
    a pmf whose index ``k`` is P(that side lost ``k`` models *before* any
    blows — a Stand & Shoot volley on the chargers, say). The round is
    resolved at each surviving strength and mixed over these two
    (independent) distributions, exactly; omitted, a side enters at full
    ``models``. The returned ``losses`` count only this round's melee
    casualties, so pre-combat losses never inflate the combat result.

    Deferred and noted, not modelled here: Always Strikes First/Last and
    the Initiative modifiers granted by special rules (Elven Reflexes) or
    weapons (a Thrusting Spear's bonus when charged) — surfaced in the
    result's notes; the break test, ranks and supporting attacks (#28),
    split-profile champions (#46), and multi-unit combats. Every fighter is
    treated as in base contact making its full Attacks. Score the round
    with :func:`combat_result`.

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
    armoury = armoury or Registry[Armour]()
    rules = rules or Registry[Rule]()
    a_strikes = _engage(a.unit, b.unit, a_weapon, armoury=armoury, rules=rules, hit_modifier=0)
    b_strikes = _engage(b.unit, a.unit, b_weapon, armoury=armoury, rules=rules, hit_modifier=0)
    a_first = _strikes_first(_effective_initiative(a), _effective_initiative(b))

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
    notes = tuple(dict.fromkeys([*a_strikes.notes, *b_strikes.notes]))
    logger.debug(
        "fight: %s vs %s, first=%s",
        a.unit.name,
        b.unit.name,
        "simultaneous" if first_striker is None else first_striker.unit.name,
    )
    return FightResult(losses=losses, first_striker=first_striker, notes=notes)


def _fell(engagement: _Engagement, fighters: int, *, targets: int) -> list[float]:
    # Casualties inflicted on the defender by ``fighters`` models striking.
    _, casualties = wound_and_casualties(
        fighters * engagement.attacks_per_model,
        p_unsaved=engagement.p_unsaved,
        p_kill=engagement.p_kill,
        wounds_per_model=engagement.defender_wounds,
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
    "combat result component not factored: rank bonus (#28)",
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
    inflicted — the only combat-result component modelled, the rest listed
    in ``notes`` (#28). For 1-Wound models wounds inflicted equal models
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
    is how many models (= wounds, for 1-Wound units) B lost, B's the
    reverse. Because the two sides are correlated under Initiative order,
    the win/draw/win split and the signed margin come from the joint, not
    from differencing the marginals.

    Returns:
        The exact win/draw/loss probabilities and signed margin distribution.
    """
    margin: dict[int, float] = {}
    p_a_wins = p_draw = p_b_wins = 0.0
    for a_lost, row in enumerate(result.losses):
        for b_lost, mass in enumerate(row):
            if mass == 0.0:
                continue
            lead = b_lost - a_lost  # A scores B's losses; B scores A's
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
