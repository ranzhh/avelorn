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
    armoury: Mapping[str, Armour],
    rules: Mapping[str, Rule],
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
    if fighters < 0:
        raise ValueError("fighters must be >= 0")
    engagement = _engage(
        attacker,
        defender,
        weapon,
        armoury=armoury or {},
        rules=rules or {},
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


@dataclass(frozen=True)
class Combatant:
    """One side entering a round of close combat.

    ``fighters`` models of ``unit`` fight with ``weapon`` (its Combat
    profile), taking an optional ``hit_modifier`` (printed sign
    convention: a penalty is negative). Rank-and-file profile only, as
    with :func:`strike_unit`.
    """

    unit: Unit
    fighters: int
    weapon: Weapon
    hit_modifier: int = 0


@dataclass(frozen=True)
class FightResult:
    """Outcome of one round of close combat between two units.

    ``losses`` is the *joint* distribution of models removed:
    ``losses[j][k]`` = P(A lost j models and B lost k). The two sides are
    correlated whenever one strikes first — a side that lost heavily strikes
    back with fewer models — so the joint, not the two marginals, is what a
    combat-result margin must be computed from. ``a_casualties`` and
    ``b_casualties`` are its marginals. ``first_striker`` is the
    :class:`Combatant` that struck first by Initiative, or None when equal
    Initiative made the blows simultaneous.
    """

    losses: list[list[float]]  # losses[a_lost][b_lost] = joint probability
    first_striker: Combatant | None
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


def fight(
    a: Combatant,
    b: Combatant,
    *,
    armoury: Mapping[str, Armour] | None = None,
    rules: Mapping[str, Rule] | None = None,
) -> FightResult:
    """Resolve one round of close combat between two single-profile units.

    Striking order is by rank-and-file Initiative (highest first): the
    higher-Initiative side strikes at full strength, its casualties are
    removed, then the lower-Initiative side strikes back **with its
    survivors** — so the loser of that exchange swings with fewer models
    (the-combat-phase: who-strikes-first, fight-on). Equal Initiative
    strikes simultaneously, with no such reduction (simultaneous-combat).

    The two sides are symmetric; only Initiative orders them. Resolution
    happens in strike order and the joint is oriented back to the ``(a, b)``
    axes the caller passed.

    Deferred and noted, not modelled here: charge/flank Initiative
    modifiers and Always Strikes First/Last (order modifiers), the break
    test, ranks and supporting attacks (#28), split-profile champions
    (#46), and multi-unit combats. Every fighter is treated as in base
    contact making its full Attacks. Score the round with
    :func:`combat_result`.

    Returns:
        The joint distribution of casualties for the round, oriented so
        ``losses[a_lost][b_lost]`` matches the combatants as passed.

    Raises:
        ValueError: either fighter count is negative (plus the matchup
            errors raised by the underlying resolution).
    """
    if a.fighters < 0 or b.fighters < 0:
        raise ValueError("fighter counts must be >= 0")
    armoury = armoury or {}
    rules = rules or {}
    a_strikes = _engage(
        a.unit, b.unit, a.weapon, armoury=armoury, rules=rules, hit_modifier=a.hit_modifier
    )
    b_strikes = _engage(
        b.unit, a.unit, b.weapon, armoury=armoury, rules=rules, hit_modifier=b.hit_modifier
    )
    initiative_a = a.unit.profiles[0][Characteristic.INITIATIVE] or 0
    initiative_b = b.unit.profiles[0][Characteristic.INITIATIVE] or 0

    if initiative_a == initiative_b:
        losses = _independent(a_strikes, a.fighters, b_strikes, b.fighters)
        first_striker: Combatant | None = None
    else:
        # The higher-Initiative side strikes first; resolve in that order,
        # then orient the joint back to the (a, b) axes.
        a_first = initiative_a > initiative_b
        striker, target = (a, b) if a_first else (b, a)
        striker_strikes, target_strikes = (
            (a_strikes, b_strikes) if a_first else (b_strikes, a_strikes)
        )
        joint = _sequenced(striker_strikes, striker.fighters, target_strikes, target.fighters)
        losses = joint if a_first else _transpose(joint)
        first_striker = striker

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
