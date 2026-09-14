"""The Shooting phase, built as a graph.

A unit's shooting is the printed attack sequence: Roll to Hit, Roll to Wound,
Make Armour Saves, Ward Saves, Remove Casualties, Make Panic Tests. Each
stage is a node whose inputs are the characteristic reads and the rule nodes
routed to it, and whose value is the roll's target together with the compiled
records the rules put on that roll. The walk enumerates the four dice stages
exactly; the fold turns per-attack outcomes into a distribution over what the
target lost. Nothing is averaged on the way.

Rules enter as source nodes. A rule that no node consumed, or that a node
held without applying, is reported in the notes; the notes are read off the
graph, not kept by hand.

Targets are treated as a unit of identical models with a shared Wounds
value; unsaved wounds accumulate into whole slain models and casualties cap
at the unit's size. Heterogeneous units still resolve off the rank-and-file
profile.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import ClassVar, NamedTuple, Protocol

from avelorn.core.distribution import Distribution, Probability
from avelorn.core.game import Phase
from avelorn.core.graph import Graph, Node, Provenance
from avelorn.tow.contingent import Contingent
from avelorn.tow.engine.armour import defender_armour
from avelorn.tow.engine.attack import (
    ArmourSave,
    AttackProfile,
    AttackResolution,
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
from avelorn.tow.engine.casualties import AttackBatch, Toll, strike_toll
from avelorn.tow.engine.characteristic_tests import pass_probability
from avelorn.tow.engine.charts import armour_save_target, shooting_hit_target, wound_target
from avelorn.tow.engine.graph import (
    MARKS,
    MULTIPLE_WOUNDS,
    SHOTS,
    Bearing,
    Kind,
    Namespace,
    routes,
)
from avelorn.tow.engine.rules import (
    AttackFacts,
    GateContext,
    MovementFacts,
    ShootingFacts,
    WeaponFacts,
    attack_marks,
    barred_worn,
    compile_rules,
    effective_armour_value,
    effective_rerolls,
    effective_volley,
    effective_ward_target,
    effective_wound_multiplier,
    factored_notes,
)
from avelorn.tow.schema.psychology import PanicCause
from avelorn.tow.schema.rule import AttackKind, RerollEffect, Rule
from avelorn.tow.schema.stage import Side, Stage
from avelorn.tow.schema.unit import Characteristic
from avelorn.tow.schema.weapon import Weapon, WeaponProfile

logger = logging.getLogger(__name__)

_NONE_IN_PLAY: Mapping[str, Rule] = {}

ATTACKER = "attacker"
TARGET = "target"
ATTACK = "attack"
REMOVE_CASUALTIES = "remove-casualties"
WOUNDS = "wounds"
CASUALTIES = "casualties"


@dataclass(frozen=True)
class StageRoll[T]:
    target: T
    modifiers: tuple[Modifier, ...] = ()
    rerolls: tuple[Reroll, ...] = ()
    transforms: tuple[Transform, ...] = ()
    held: frozenset[str] = frozenset()


class Shots(NamedTuple):
    count: int
    held: frozenset[str] = frozenset()


class Damage(NamedTuple):
    wounds: Distribution[int] | None
    held: frozenset[str] = frozenset()


class _Held(Protocol):
    @property
    def held(self) -> frozenset[str]: ...


def _provenance(value: _Held) -> Provenance:
    return Provenance(unfactored=value.held)


@dataclass(frozen=True)
class AttackSequence:
    graph: Graph
    shots: Node[Shots]
    roll_to_hit: Node[StageRoll[int]]
    roll_to_wound: Node[StageRoll[int | None]]
    make_armour_saves: Node[StageRoll[int | None]]
    ward_saves: Node[StageRoll[int | None]]
    attack: Node[AttackResolution]
    models: Node[int | None]
    removed: Node[Distribution[Toll]]
    wounds: Node[Distribution[int]]
    casualties: Node[Distribution[int]]

    @property
    def hit_target(self) -> int:
        """The To Hit target the walk used, unconditional modifiers applied."""
        reported = self.attack.value.hit_target
        return reported if isinstance(reported, int) else self.roll_to_hit.value.target

    @property
    def save_target(self) -> int | None:
        """The armour save the walk used; a save worsened past 6+ is no save."""
        reported = self.attack.value.save_target
        return reported if isinstance(reported, int) and reported <= 6 else None


@dataclass(frozen=True)
class Shooting(AttackSequence):
    attacker: Node[Contingent]
    target: Node[Contingent]
    weapon: Node[Weapon]
    rules: tuple[Node[Bearing], ...]
    notes: tuple[str, ...]


def _attack(
    hit: Node[StageRoll[int]],
    wound: Node[StageRoll[int | None]],
    save: Node[StageRoll[int | None]],
    ward: Node[StageRoll[int | None]],
) -> AttackResolution:
    stages = (hit.value, wound.value, save.value, ward.value)
    return resolve_attack(
        AttackProfile.shooting(
            hit_target=hit.value.target,
            wound_target=roll_target(wound.value.target),
            save_target=roll_target(save.value.target),
            ward_target=roll_target(ward.value.target),
        ),
        [record for stage in stages for record in stage.modifiers],
        [record for stage in stages for record in stage.transforms],
        [record for stage in stages for record in stage.rerolls],
    )


def _remove_casualties(
    shots: Node[Shots],
    attack: Node[AttackResolution],
    wounds_per_model: Node[int],
    models: Node[int | None],
    damage: Node[Damage],
) -> Distribution[Toll]:
    batch = AttackBatch(
        shots.value.count, attack.value.p_unsaved, attack.value.p_of(Outcome.INSTANT_KILL)
    )
    return strike_toll(
        [batch],
        wounds_per_model=wounds_per_model.value,
        targets=models.value,
        damage=damage.value.wounds,
    )


def _wounds(removed: Node[Distribution[Toll]]) -> Distribution[int]:
    return removed.value.map(lambda toll: toll.wounds)


def _felled(removed: Node[Distribution[Toll]]) -> Distribution[int]:
    return removed.value.map(lambda toll: toll.felled)


def _sequence(
    graph: Graph,
    shots: Node[Shots],
    hit: Node[StageRoll[int]],
    wound: Node[StageRoll[int | None]],
    save: Node[StageRoll[int | None]],
    ward: Node[StageRoll[int | None]],
    wounds_per_model: Node[int],
    models: Node[int | None],
    damage: Node[Damage],
) -> AttackSequence:
    attack = graph.node(ATTACK, Kind.WALK, "Attack", hit, wound, save, ward, body=_attack)
    removed = graph.node(
        REMOVE_CASUALTIES,
        Kind.FOLD,
        "Remove Casualties",
        shots,
        attack,
        wounds_per_model,
        models,
        damage,
        body=_remove_casualties,
    )
    wounds = graph.node(WOUNDS, Kind.FOLD, "Unsaved wounds", removed, body=_wounds)
    casualties = graph.node(CASUALTIES, Kind.FOLD, "Casualties", removed, body=_felled)
    logger.debug(
        "%d shots at p_unsaved=%.3f -> %d casualty outcomes",
        shots.value.count,
        attack.value.p_unsaved,
        len(casualties.value.mass),
    )
    return AttackSequence(
        graph, shots, hit, wound, save, ward, attack, models, removed, wounds, casualties
    )


class _Given(NamedTuple):
    modifiers: tuple[Modifier, ...]
    transforms: tuple[Transform, ...]
    rerolls: tuple[Reroll, ...]

    def at[T](self, stage: Stage, target: T) -> StageRoll[T]:
        return StageRoll(
            target,
            tuple(m for m in self.modifiers if m.lands_on is stage),
            tuple(r for r in self.rerolls if r.stage is stage),
            tuple(t for t in self.transforms if t.stage is stage),
        )


def _given_hit(skill: Node[int], modifier: Node[int], given: Node[_Given]) -> StageRoll[int]:
    return given.value.at(Stage.ROLL_TO_HIT, shooting_hit_target(skill.value, modifier.value))


def _given_wound(
    strength: Node[int], toughness: Node[int], given: Node[_Given]
) -> StageRoll[int | None]:
    return given.value.at(Stage.ROLL_TO_WOUND, wound_target(strength.value, toughness.value))


def _given_save(
    armour_value: Node[int | None], armour_piercing: Node[int], given: Node[_Given]
) -> StageRoll[int | None]:
    target = armour_save_target(armour_value.value, armour_piercing.value)
    return given.value.at(Stage.MAKE_ARMOUR_SAVES, target)


def _given_ward(ward: Node[int | None], given: Node[_Given]) -> StageRoll[int | None]:
    return given.value.at(Stage.WARD_SAVES, ward.value)


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
    damage: Distribution[int] | None = None,
) -> AttackSequence:
    """Resolve identical shooting attacks from bare numbers and compiled records.

    The characteristics are given, and ``modifiers``, ``transforms`` and
    ``rerolls`` are already-compiled records placed on the stage each names.
    ``targets`` caps casualties at the unit's size when known; ``damage`` is
    what each unsaved wound inflicts (Multiple Wounds), None for one.

    Returns:
        The resolved sequence.

    Raises:
        ValueError: ``shots`` or ``targets`` is negative, or
            ``wounds_per_model`` is less than 1.
    """
    if shots < 0:
        raise ValueError("shots must be >= 0")
    if targets is not None and targets < 0:
        raise ValueError("targets must be >= 0")
    if wounds_per_model < 1:
        raise ValueError("wounds_per_model must be >= 1")
    graph = Graph()
    skill = graph.source("ballistic-skill", Kind.READ, "Ballistic Skill", ballistic_skill)
    modifier = graph.source("hit-modifier", Kind.CONDITION, "To Hit modifier", hit_modifier)
    s = graph.source("strength", Kind.READ, "Strength", strength)
    t = graph.source("toughness", Kind.READ, "Toughness", toughness)
    armour = graph.source("armour-value", Kind.READ, "Armour Value", armour_value)
    piercing = graph.source("armour-piercing", Kind.READ, "Armour Piercing", armour_piercing)
    ward = graph.source("ward-target", Kind.READ, "Ward save", ward_target)
    given = graph.source(
        "records",
        Kind.RULES,
        "Compiled records",
        _Given(tuple(modifiers), tuple(transforms), tuple(rerolls)),
    )
    hit = graph.node(
        Stage.ROLL_TO_HIT.value, Kind.STAGE, "Roll to Hit", skill, modifier, given, body=_given_hit
    )
    wound = graph.node(
        Stage.ROLL_TO_WOUND.value, Kind.STAGE, "Roll to Wound", s, t, given, body=_given_wound
    )
    save = graph.node(
        Stage.MAKE_ARMOUR_SAVES.value,
        Kind.STAGE,
        "Make Armour Saves",
        armour,
        piercing,
        given,
        body=_given_save,
    )
    warded = graph.node(
        Stage.WARD_SAVES.value, Kind.STAGE, "Ward Saves", ward, given, body=_given_ward
    )
    count = graph.source(SHOTS, Kind.COUNT, "Shots", Shots(shots))
    per_model = graph.source("target.wounds", Kind.READ, "Wounds", wounds_per_model)
    models = graph.source("target.models", Kind.READ, "Models", targets)
    multiplier = graph.source(MULTIPLE_WOUNDS, Kind.EFFECTIVE, "Multiple Wounds", Damage(damage))
    return _sequence(graph, count, hit, wound, save, warded, per_model, models, multiplier)


def _at_long_range(profile: WeaponProfile, distance: int | None) -> bool | None:
    if distance is None or not isinstance(profile.range, int):
        return None
    return distance > profile.range / 2


def _engagement_conditions(
    shooter: Contingent,
    weapon: Weapon,
    profile: WeaponProfile,
    distance: int | None,
    force_short_range: bool,
    stand_and_shoot: bool,
) -> GateContext:
    # The weapon is the one chosen for the shot, which need not be the one in
    # hand, so it is passed rather than read off the shooter. A shot forced
    # short, or a Stand & Shoot reaction, is never at long range.
    return GateContext(
        wielding=WeaponFacts(type=weapon.weapon_type, name=weapon.name),
        worn=shooter.armour_facts,
        movement=MovementFacts(moved=shooter.movement.moved),
        shooting=ShootingFacts(
            at_long_range=False if force_short_range else _at_long_range(profile, distance),
            stand_and_shoot=stand_and_shoot,
        ),
    )


def _shooting_weapon(shooter: Node[Contingent]) -> Weapon:
    return shooter.value.shooting_weapon()


def _missile_profile(weapon: Node[Weapon]) -> WeaponProfile:
    profile = weapon.value.missile_profile
    if profile is None:
        raise ValueError(f"{weapon.value.name} has no missile profile; it cannot shoot")
    return profile


def _ballistic_skill(shooter: Node[Contingent]) -> int:
    value = shooter.value.unit.main[Characteristic.BALLISTIC_SKILL]
    if value is None:
        raise ValueError(f"{shooter.value.unit.name} has no Ballistic Skill; it cannot shoot")
    return value


def _toughness(target: Node[Contingent]) -> int:
    value = target.value.unit.main[Characteristic.TOUGHNESS]
    if value is None:
        raise ValueError(f"{target.value.unit.name} has no Toughness; it cannot be wounded")
    return value


def _strength(
    shooter: Node[Contingent], weapon: Node[Weapon], profile: Node[WeaponProfile]
) -> int:
    wielder = shooter.value.unit.main[Characteristic.STRENGTH]
    if profile.value.strength.is_relative and wielder is None:
        raise ValueError(
            f"{weapon.value.name} shoots at the wielder's Strength, but "
            f"{shooter.value.unit.name} has none"
        )
    return profile.value.strength.resolve(wielder or 0)


def _wounds_per_model(target: Node[Contingent]) -> int:
    # A profile with no printed Wounds ("-") is a single-Wound model.
    return target.value.unit.main[Characteristic.WOUNDS] or 1


def _models(target: Node[Contingent]) -> int:
    return target.value.models


def _conditions(
    shooter: Node[Contingent],
    weapon: Node[Weapon],
    profile: Node[WeaponProfile],
    distance: Node[int | None],
    force_short_range: Node[bool],
    stand_and_shoot: Node[bool],
) -> GateContext:
    return _engagement_conditions(
        shooter.value,
        weapon.value,
        profile.value,
        distance.value,
        force_short_range.value,
        stand_and_shoot.value,
    )


def _borne(rules: Sequence[Node[Bearing]], side: Side, origin: Namespace) -> list[Rule]:
    return [n.value.rule for n in rules if n.value.side is side and n.value.origin is origin]


def _incoming(
    target: Node[Contingent],
    conditions: Node[GateContext],
    profile: Node[WeaponProfile],
    *rules: Node[Bearing],
) -> GateContext:
    weapon_rules = {r.name: r for r in _borne(rules, Side.ATTACKER, Namespace.WEAPON)}
    marks = attack_marks(
        profile.value.special_rules, weapon_rules, _borne(rules, Side.ATTACKER, Namespace.UNIT)
    )
    return GateContext(
        wielding=target.value.weapon_facts,
        worn=target.value.armour_facts,
        target_of=AttackFacts(
            kind=AttackKind.SHOOTING,
            magical=marks.magical,
            flaming=marks.flaming,
            at_long_range=conditions.value.shooting.at_long_range,
        ),
    )


def _held(rules: Sequence[Node[Bearing]], *factored: Sequence[str]) -> frozenset[str]:
    names = {name for names in factored for name in names}
    return frozenset(n.id for n in rules if n.value.rule.name not in names)


def _shots(
    shooter: Node[Contingent], conditions: Node[GateContext], *rules: Node[Bearing]
) -> Shots:
    # Only the front rank fires on flat ground; Volley Fire adds half of each
    # rank behind it, rounding up.
    volley = effective_volley([n.value.rule for n in rules], conditions.value)
    count = shooter.value.formation.files
    if volley.fires:
        count += sum((rank + 1) // 2 for rank in shooter.value.formation.rear_rank_sizes)
    return Shots(count, _held(rules, volley.factored))


def _multiple_wounds(conditions: Node[GateContext], *rules: Node[Bearing]) -> Damage:
    multiplier = effective_wound_multiplier([n.value.rule for n in rules], conditions.value)
    return Damage(multiplier.wounds, _held(rules, multiplier.factored))


def _stage[T](
    stage: Stage,
    target: T,
    conditions: GateContext,
    incoming: GateContext,
    rules: Sequence[Node[Bearing]],
    *factored: Sequence[str],
) -> StageRoll[T]:
    # Each rule compiles from its bearer's seat under its bearer's facts. Only
    # the records landing on this stage are kept; a rule reaching two stages is
    # routed to both and compiled at each. ``factored`` adds the names other
    # folds at this stage applied, so they are not reported as held.
    modifiers: list[Modifier] = []
    rerolls: list[Reroll] = []
    transforms: list[Transform] = []
    applied: set[str] = {name for names in factored for name in names}
    for node in rules:
        bearing = node.value
        facts = conditions if bearing.side is Side.ATTACKER else incoming
        compiled = compile_rules(
            [bearing.rule.name],
            {bearing.rule.name: bearing.rule},
            facts,
            seat=bearing.side,
            grants=bearing.grants,
        )
        rerolled = effective_rerolls([bearing.rule], facts, seat=bearing.side)
        modifiers.extend(m for m in compiled.modifiers if m.lands_on is stage)
        transforms.extend(t for t in compiled.transforms if t.stage is stage)
        rerolls.extend(r for r in rerolled.rerolls if r.stage is stage)
        applied.update(compiled.factored, rerolled.factored)
    held = frozenset(n.id for n in rules if n.value.rule.name not in applied)
    return StageRoll(target, tuple(modifiers), tuple(rerolls), tuple(transforms), held)


def _roll_to_hit(
    skill: Node[int],
    modifier: Node[int],
    conditions: Node[GateContext],
    incoming: Node[GateContext],
    *rules: Node[Bearing],
) -> StageRoll[int]:
    target = shooting_hit_target(skill.value, modifier.value)
    return _stage(Stage.ROLL_TO_HIT, target, conditions.value, incoming.value, rules)


def _roll_to_wound(
    strength: Node[int],
    toughness: Node[int],
    conditions: Node[GateContext],
    incoming: Node[GateContext],
    *rules: Node[Bearing],
) -> StageRoll[int | None]:
    target = wound_target(strength.value, toughness.value)
    return _stage(Stage.ROLL_TO_WOUND, target, conditions.value, incoming.value, rules)


def _make_armour_saves(
    target: Node[Contingent],
    profile: Node[WeaponProfile],
    conditions: Node[GateContext],
    incoming: Node[GateContext],
    *rules: Node[Bearing],
) -> StageRoll[int | None]:
    # A barred piece (Requires Two Hands' shield) is withdrawn before any
    # value is read. The unit's rules fold first, the weapon in use's on the
    # result.
    unit_rules = _borne(rules, Side.TARGET, Namespace.UNIT)
    weapon_rules = _borne(rules, Side.TARGET, Namespace.WEAPON)
    barred = barred_worn(weapon_rules, incoming.value)
    usable = [piece for piece in target.value.loadout.armour if piece.name not in barred.names]
    printed = defender_armour(usable)
    unit_fold = effective_armour_value(printed, unit_rules, incoming.value)
    after_unit = None if printed is None else unit_fold.value
    weapon_fold = effective_armour_value(after_unit, weapon_rules, incoming.value)
    armour_value = None if printed is None else weapon_fold.value
    return _stage(
        Stage.MAKE_ARMOUR_SAVES,
        armour_save_target(armour_value, profile.value.armour_piercing),
        conditions.value,
        incoming.value,
        rules,
        unit_fold.factored,
        weapon_fold.factored,
        barred.factored,
    )


def _ward_saves(
    conditions: Node[GateContext], incoming: Node[GateContext], *rules: Node[Bearing]
) -> StageRoll[int | None]:
    # Wards never stack: the best of the unit's and the weapon's grants applies.
    unit_ward = effective_ward_target(_borne(rules, Side.TARGET, Namespace.UNIT), incoming.value)
    weapon_ward = effective_ward_target(
        _borne(rules, Side.TARGET, Namespace.WEAPON), incoming.value
    )
    granted = [t for t in (unit_ward.target, weapon_ward.target) if t is not None]
    return _stage(
        Stage.WARD_SAVES,
        min(granted) if granted else None,
        conditions.value,
        incoming.value,
        rules,
        unit_ward.factored,
        weapon_ward.factored,
    )


def _bear(
    graph: Graph,
    owner: str,
    rules: Sequence[Rule],
    side: Side,
    origin: Namespace,
    grants: Mapping[str, Rule],
) -> list[Node[Bearing]]:
    return [
        graph.source(
            f"{owner}.rule.{rule.id}", Kind.RULE, rule.name, Bearing(rule, side, origin, grants)
        )
        for rule in rules
    ]


def _notes(
    graph: Graph,
    rules: Sequence[Node[Bearing]],
    attacker: Contingent,
    target: Contingent,
    weapon: Weapon,
) -> tuple[str, ...]:
    consumed = {i for node in graph.nodes.values() for i in node.inputs}
    held = graph.provenance.unfactored
    factored = {n.id for n in rules if n.id in consumed and n.id not in held}
    notes: list[str] = []
    for side, unit in ((Side.ATTACKER, attacker), (Side.TARGET, target)):
        borne = [n for n in rules if n.value.side is side and n.value.origin is Namespace.UNIT]
        names = {n.value.rule.name for n in borne if n.id in factored}
        notes.extend(
            f"special rule not factored: {name} ({unit.unit.name})"
            for name in unit.unit.special_rules
            if name not in names
        )
        notes.extend(
            factored_notes(unit.loadout.rules, names, unit.unit.name, unit.loadout.granted_rules)
        )
    weapon_borne = {
        n.value.rule.name: n
        for n in rules
        if n.value.side is Side.ATTACKER and n.value.origin is Namespace.WEAPON
    }
    profile = weapon.missile_profile
    for name in () if profile is None else profile.special_rules:
        node = weapon_borne.get(name)
        if node is None or node.id not in factored:
            notes.append(f"weapon rule not factored: {name} ({weapon.name})")
    notes.extend(
        f"core rule not factored: {n.value.rule.name}"
        for n in rules
        if n.value.origin is Namespace.CORE and n.id not in factored
    )
    if weapon.notes is not None:
        notes.append(f"weapon notes not factored ({weapon.name}): {weapon.notes}")
    return tuple(notes)


def shoot_unit(
    attacker: Contingent,
    defender: Contingent,
    *,
    phase_rules: Mapping[str, Rule] = _NONE_IN_PLAY,
    distance: int | None = None,
    hit_modifier: int = 0,
    force_short_range: bool = False,
    stand_and_shoot: bool = False,
) -> Shooting:
    """Resolve ``attacker`` shooting at ``defender``.

    The front rank fires, with the missile profile of the weapon the attacker
    shoots with (``attacker.shooting_weapon()``); Volley Fire adds half of each
    rear rank while the unit stands still and is not reacting to a charge.
    ``phase_rules`` are the chapter rules in force. ``distance`` is the range
    to the target; left None, a rule gated on range stays unapplied and is
    noted. ``force_short_range`` treats the shot as within half range;
    ``stand_and_shoot`` marks a charge reaction, which forbids Volley Fire.

    The steps that read the units raise ValueError when the attacker has no
    missile weapon to shoot with, the weapon has no missile profile, the
    attacker profile has no Ballistic Skill, the defender profile has no
    Toughness, or the weapon shoots at the wielder's Strength and the
    attacker profile has none.

    Returns:
        The resolved shooting, its graph and its notes.
    """
    graph = Graph()
    shooter = graph.source(ATTACKER, Kind.UNIT, attacker.unit.name, attacker)
    target = graph.source(TARGET, Kind.UNIT, defender.unit.name, defender)
    weapon = graph.node("attacker.weapon", Kind.WEAPON, "Weapon", shooter, body=_shooting_weapon)
    profile = graph.node(
        "attacker.missile-profile", Kind.WEAPON, "Missile profile", weapon, body=_missile_profile
    )
    skill = graph.node(
        "attacker.ballistic-skill", Kind.READ, "Ballistic Skill", shooter, body=_ballistic_skill
    )
    toughness = graph.node("target.toughness", Kind.READ, "Toughness", target, body=_toughness)
    strength = graph.node(
        "attacker.strength", Kind.READ, "Strength", shooter, weapon, profile, body=_strength
    )
    range_ = graph.source("distance", Kind.CONDITION, "Distance", distance)
    modifier = graph.source("hit-modifier", Kind.CONDITION, "To Hit modifier", hit_modifier)
    short = graph.source("short-range", Kind.CONDITION, "Forced short range", force_short_range)
    reaction = graph.source("stand-and-shoot", Kind.CONDITION, "Stand & Shoot", stand_and_shoot)
    conditions = graph.node(
        "attacker.conditions",
        Kind.CONDITION,
        "Conditions",
        shooter,
        weapon,
        profile,
        range_,
        short,
        reaction,
        body=_conditions,
    )

    in_use = attacker.loadout.weapon_rules
    weapon_rules = [in_use[name] for name in profile.value.special_rules if name in in_use]
    granted, foe_granted = attacker.loadout.granted_rules, defender.loadout.granted_rules
    in_force = [phase_rules[name] for name in sorted(phase_rules)]
    rules: list[Node[Bearing]] = [
        *_bear(graph, "attacker.weapon", weapon_rules, Side.ATTACKER, Namespace.WEAPON, granted),
        *_bear(graph, ATTACKER, attacker.loadout.rules, Side.ATTACKER, Namespace.UNIT, granted),
        *_bear(graph, TARGET, defender.loadout.rules, Side.TARGET, Namespace.UNIT, foe_granted),
        *_bear(
            graph,
            "target.weapon",
            defender.in_hand_rules(),
            Side.TARGET,
            Namespace.WEAPON,
            foe_granted,
        ),
        *_bear(graph, "core", in_force, Side.ATTACKER, Namespace.CORE, {}),
    ]
    routed: dict[str, list[Node[Bearing]]] = {}
    for node in rules:
        for consumer in routes(node.value):
            routed.setdefault(consumer, []).append(node)

    def to(consumer: str) -> list[Node[Bearing]]:
        return routed.get(consumer, [])

    incoming = graph.node(
        "target.incoming",
        Kind.CONDITION,
        "Incoming attack",
        target,
        conditions,
        profile,
        *to(MARKS),
        body=_incoming,
    )
    shots = graph.node(
        SHOTS,
        Kind.COUNT,
        "Shots",
        shooter,
        conditions,
        *to(SHOTS),
        body=_shots,
        provenance=_provenance,
    )
    damage = graph.node(
        MULTIPLE_WOUNDS,
        Kind.EFFECTIVE,
        "Multiple Wounds",
        conditions,
        *to(MULTIPLE_WOUNDS),
        body=_multiple_wounds,
        provenance=_provenance,
    )
    hit = graph.node(
        Stage.ROLL_TO_HIT.value,
        Kind.STAGE,
        "Roll to Hit",
        skill,
        modifier,
        conditions,
        incoming,
        *to(Stage.ROLL_TO_HIT.value),
        body=_roll_to_hit,
        provenance=_provenance,
    )
    wound = graph.node(
        Stage.ROLL_TO_WOUND.value,
        Kind.STAGE,
        "Roll to Wound",
        strength,
        toughness,
        conditions,
        incoming,
        *to(Stage.ROLL_TO_WOUND.value),
        body=_roll_to_wound,
        provenance=_provenance,
    )
    save = graph.node(
        Stage.MAKE_ARMOUR_SAVES.value,
        Kind.STAGE,
        "Make Armour Saves",
        target,
        profile,
        conditions,
        incoming,
        *to(Stage.MAKE_ARMOUR_SAVES.value),
        body=_make_armour_saves,
        provenance=_provenance,
    )
    ward = graph.node(
        Stage.WARD_SAVES.value,
        Kind.STAGE,
        "Ward Saves",
        conditions,
        incoming,
        *to(Stage.WARD_SAVES.value),
        body=_ward_saves,
        provenance=_provenance,
    )
    per_model = graph.node("target.wounds", Kind.READ, "Wounds", target, body=_wounds_per_model)
    models = graph.node("target.models", Kind.READ, "Models", target, body=_models)
    logger.debug(
        "resolving %d %s (BS %d) shooting %s at %s (T %d), S %d AP %d",
        shots.value.count,
        attacker.unit.name,
        skill.value,
        weapon.value.name,
        defender.unit.name,
        toughness.value,
        strength.value,
        profile.value.armour_piercing,
    )
    sequence = _sequence(graph, shots, hit, wound, save, ward, per_model, models, damage)
    return Shooting(
        graph=graph,
        shots=shots,
        roll_to_hit=hit,
        roll_to_wound=wound,
        make_armour_saves=save,
        ward_saves=ward,
        attack=sequence.attack,
        models=models,
        removed=sequence.removed,
        wounds=sequence.wounds,
        casualties=sequence.casualties,
        attacker=shooter,
        target=target,
        weapon=weapon,
        rules=tuple(rules),
        notes=_notes(graph, rules, attacker, defender, weapon.value),
    )


@dataclass(frozen=True)
class PanicTest(Roll):
    """The Make Panic Tests step's dice: 2D6 against the unit's Leadership.

    Rolled once for the whole unit, so no single natural face exists and a
    ``natural:`` trigger cannot name it. The printed bounds (a double 6 always
    fails, a double 1 always passes) live in the characteristic-test procedure.
    """

    leadership: int | None
    stage: ClassVar[Stage] = Stage.MAKE_PANIC_TESTS

    def chance(self) -> Fraction:
        """The probability the test passes; 0 for no Leadership at all.

        Returns:
            The exact pass probability.
        """
        return pass_probability(Characteristic.LEADERSHIP, self.leadership)


@dataclass(frozen=True)
class PanicResult:
    p_test: Probability  # lost more than 25% of start-of-phase models (and survived)
    p_holds: Probability  # never tested, or tested and passed
    p_falls_back: Probability  # failed with more than half its battle strength left
    p_flees: Probability  # failed at half its battle strength or less
    p_destroyed: Probability  # every model lost: no unit remains to test
    reroll_from: str | None = None  # the rule that re-rolls a failed test, if any


def panic_outcomes(
    casualties: Distribution[int],
    size: int,
    defender: Contingent,
    rules: Sequence[Rule],
    *,
    battle_strength: int | None = None,
) -> PanicResult:
    """Resolve the panic step for a casualty distribution.

    A unit that lost more than a quarter of its ``size`` tests against its
    Leadership; a re-roll effect on this step among ``rules`` re-rolls a
    failed test once. ``battle_strength`` is the model count at the start of
    the battle, which governs the Fall Back or Flee split; it defaults to
    ``size``.

    Returns:
        The exact probabilities of each panic outcome.

    Raises:
        ValueError: ``size`` is zero, or ``battle_strength`` is below it.
    """
    if size == 0:
        raise ValueError("panic needs the target unit's size")
    battle = battle_strength if battle_strength is not None else size
    if battle < size:
        raise ValueError(f"battle strength ({battle}) cannot be below current size ({size})")
    test = PanicTest(defender.unit.highest(Characteristic.LEADERSHIP))
    p_pass = test.chance()
    reroll_from = _reroll_grant(rules, PanicCause.HEAVY_CASUALTIES)
    if reroll_from is not None:
        p_pass = p_pass + (1 - p_pass) * p_pass
    zero = p_pass * 0
    tested = holds = falls_back = flees = destroyed = zero
    for killed, mass in casualties.mass.items():
        if killed == size:
            destroyed += mass
        elif killed * 4 > size:  # "more than a quarter (25%)"
            tested += mass
            holds += mass * p_pass
            remaining = size - killed
            failed = mass * (1 - p_pass)
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


def _reroll_grant(rules: Sequence[Rule], cause: PanicCause) -> str | None:
    # One grant is all a test can ever use.
    for rule in rules:
        for effect in rule.effects:
            if (
                isinstance(effect, RerollEffect)
                and effect.reroll is Stage.MAKE_PANIC_TESTS
                and (not effect.causes or cause in effect.causes)
            ):
                return rule.name
    return None


def _make_panic_tests(
    casualties: Node[Distribution[int]],
    target: Node[Contingent],
    battle_strength: Node[int | None],
    *rules: Node[Bearing],
) -> PanicResult:
    return panic_outcomes(
        casualties.value,
        target.value.models,
        target.value,
        [n.value.rule for n in rules],
        battle_strength=battle_strength.value,
    )


def make_panic_tests(
    shooting: Shooting, *, battle_strength: int | None = None
) -> Node[PanicResult]:
    strength = shooting.graph.source(
        "battle-strength", Kind.CONDITION, "Battle strength", battle_strength
    )
    routed = [n for n in shooting.rules if Stage.MAKE_PANIC_TESTS.value in routes(n.value)]
    return shooting.graph.node(
        Stage.MAKE_PANIC_TESTS.value,
        Kind.TEST,
        "Make Panic Tests",
        shooting.casualties,
        shooting.target,
        strength,
        *routed,
        body=_make_panic_tests,
    )


@dataclass(frozen=True)
class ShootingPhase(Phase):
    in_play: Mapping[str, Rule]

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
    ) -> Shooting:
        return shoot_unit(
            attacker,
            defender,
            phase_rules=self.in_play,
            distance=distance,
            hit_modifier=hit_modifier,
        )

    def make_panic_tests(
        self, shooting: Shooting, *, battle_strength: int | None = None
    ) -> Node[PanicResult]:
        return make_panic_tests(shooting, battle_strength=battle_strength)
