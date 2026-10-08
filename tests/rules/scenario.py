"""A fight fielded from data/ and resolved; only :func:`resolve` knows which engine answers."""

import copy
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from avelorn.core.distribution import Distribution, Probability
from avelorn.core.registry import Registry
from avelorn.tow.contingent import Charge, ChargeArc, Contingent, Movement
from avelorn.tow.data import TOWRepository
from avelorn.tow.fielding import SHIELD, Fielding, Held
from avelorn.tow.phases.combat import (
    CombatPhase,
    FightResult,
    SideBreak,
    break_test,
    combat_result,
    fight,
)
from avelorn.tow.phases.movement import StandAndShoot, charge
from avelorn.tow.programs import ROUND, VOLLEY, Evaluated, load_program
from avelorn.tow.schema import stage
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.weapon import Weapon
from avelorn.tow.steps import Retreat

REPO = TOWRepository()

CHAPTERS = (Phase.SHOOTING, Phase.COMBAT)

INITIATIVES = range(10, 0, -1)


class Kind(StrEnum):
    """What the attacker does; STRIKE is the attacker's blows in a round."""

    SHOOT = "shoot"
    STRIKE = "strike"
    FIGHT = "fight"
    STAND_AND_SHOOT = "charge-with-stand-and-shoot"
    PANIC = "panic"
    BREAK = "break"


ROUNDS = frozenset({Kind.FIGHT, Kind.BREAK})

IN_A_ROUND = ROUNDS | {Kind.STRIKE}


class Role(StrEnum):
    ATTACKER = "attacker"
    DEFENDER = "defender"


_SIDES = {Role.ATTACKER: stage.Side.ATTACKER, Role.DEFENDER: stage.Side.TARGET}


class Carrier(StrEnum):
    MODEL = "model"
    WEAPON = "weapon"


@dataclass(frozen=True)
class Ref:
    """A rule by slug, with the X its printed name takes."""

    slug: str
    x: str | int | None = None


@dataclass(frozen=True)
class Side:
    """A datasheet fielded at ``models``; ``charged`` is the inches of a front-arc charge.

    In combat it fights with ``weapon``, and with its shield when it wears one
    unless ``shield`` is False.
    """

    unit: str
    models: int
    weapon: str | None = None
    frontage: int | None = None
    moved: bool = False
    charged: int | None = None
    equipment: tuple[str, ...] = ()
    rules: tuple[Ref, ...] = ()
    weapon_rules: tuple[Ref, ...] = ()
    dropped: frozenset[str] = frozenset()
    shield: bool = True


@dataclass(frozen=True)
class Scenario:
    """Two sides and what the attacker does; in a Stand & Shoot the defender fires.

    A fight or a break test names whether its round is the combat's first. A
    strike may, and with ``first_round`` unset its round is not the first.
    """

    kind: Kind
    attacker: Side
    defender: Side
    distance: int | None = None
    first_round: bool | None = None
    dropped: frozenset[str] = frozenset()

    def side(self, role: Role) -> Side:
        return self.attacker if role is Role.ATTACKER else self.defender

    def _with_side(self, role: Role, side: Side) -> "Scenario":
        return replace(self, **{role.value: side})

    def adding(
        self,
        slug: str,
        role: Role,
        carrier: Carrier = Carrier.MODEL,
        x: str | int | None = None,
    ) -> "Scenario":
        """This scenario with rule ``slug`` added to one side's models or weapon in hand.

        Returns:
            The changed scenario.
        """
        side, ref = self.side(role), Ref(slug, x)
        if carrier is Carrier.WEAPON:
            return self._with_side(role, replace(side, weapon_rules=(*side.weapon_rules, ref)))
        return self._with_side(role, replace(side, rules=(*side.rules, ref)))

    def without(self, slug: str, role: Role | None = None) -> "Scenario":
        """This scenario with rule ``slug`` taken off one side, or out of the chapter rules.

        Returns:
            The changed scenario.
        """
        if role is None:
            return replace(self, dropped=self.dropped | {slug})
        side = self.side(role)
        return self._with_side(role, replace(side, dropped=side.dropped | {slug}))


@dataclass(frozen=True)
class Break:
    gives_ground: Probability
    falls_back: Probability
    breaks: Probability


@dataclass(frozen=True)
class Panic:
    tested: Probability
    holds: Probability
    falls_back: Probability
    flees: Probability
    destroyed: Probability


@dataclass(frozen=True)
class Outcome:
    """What a scenario resolved to; ``margin`` is the attacker's lead in combat result."""

    attacks: int | None = None
    unsaved: Probability | None = None
    casualties: Mapping[int, Probability] = field(default_factory=dict)
    attacker_casualties: Mapping[int, Probability] = field(default_factory=dict)
    initiative: Mapping[Role, int] = field(default_factory=dict)
    margin: Mapping[int, Probability] = field(default_factory=dict)
    breaks: Mapping[Role, Break] = field(default_factory=dict)
    panic: Panic | None = None


def resolve(scenario: Scenario) -> Outcome:
    """Resolve ``scenario``: a volley, its Panic test or a strike on the graph, the rest on legacy.

    A program is read in the lane where every rule a player may decline is taken.

    Returns:
        The outcome its kind decides.

    Raises:
        ValueError: a fight or break with no ``first_round``, a kind fought in no round
            with one, a Stand & Shoot whose attacker did not charge, or a dropped
            chapter rule that is not one.
    """
    if scenario.kind in ROUNDS and scenario.first_round is None:
        raise ValueError(f"a {scenario.kind} needs first_round")
    if scenario.kind not in IN_A_ROUND and scenario.first_round is not None:
        raise ValueError(f"first_round is an input of a round, not of {scenario.kind}")
    unknown = scenario.dropped - {
        rule.id for phase in CHAPTERS for rule in _chapter(phase).values()
    }
    if unknown:
        raise ValueError(f"not a chapter rule with effects: {sorted(unknown)}")
    attacker, defender = _field(scenario.attacker), _field(scenario.defender)
    shooting = _chapter(Phase.SHOOTING, scenario.dropped)
    combat = _chapter(Phase.COMBAT, scenario.dropped)
    match scenario.kind:
        case Kind.SHOOT:
            return _shot(_volley(attacker, defender, scenario), defender.models)
        case Kind.PANIC:
            volley = _volley(attacker, defender, scenario)
            return replace(_shot(volley, defender.models), panic=_panicked(volley))
        case Kind.STRIKE:
            return _struck(_round(attacker, defender, scenario), attacker.models, defender.models)
        case Kind.FIGHT | Kind.BREAK:
            fought = fight(
                attacker, defender, first_round=scenario.first_round, phase_rules=combat
            )
            outcome = _fought(fought)
            if scenario.kind is Kind.FIGHT:
                return outcome
            broken = break_test(combat_result(fought), attacker, defender)
            return replace(
                outcome,
                breaks={Role.ATTACKER: _break(broken.a), Role.DEFENDER: _break(broken.b)},
            )
        case Kind.STAND_AND_SHOOT:
            move = attacker.movement.charge
            if move is None:
                raise ValueError("a Stand & Shoot answers a charge; the attacker must charge")
            engagement = charge(attacker, defender, move, shooting_rules=shooting)
            reaction = engagement.react(StandAndShoot())
            assert reaction is not None
            fought = CombatPhase(in_play=combat).fight(engagement)
            return replace(_fought(fought), attacks=reaction.shots)


def _volley(attacker: Contingent, defender: Contingent, scenario: Scenario) -> Evaluated:
    fielded = {
        stage.Side.ATTACKER: Fielding.of(attacker, attacker.shooting_weapon().name),
        stage.Side.TARGET: Fielding.of(defender),
    }
    return _taken(
        load_program(VOLLEY, _rules(scenario))
        .built(fielded)
        .evaluate(
            {
                "distance": scenario.distance,
                "can-shoot": True,
                "line-of-sight": True,
                "attacker/moved": attacker.movement.moved,
                "attacker/standing": fielded[stage.Side.ATTACKER].standing(attacker.models),
                "target/standing": fielded[stage.Side.TARGET].standing(defender.models),
                "target/models-at-start-of-phase": defender.models,
                "target/battle-strength": defender.models,
            }
        )
    )


def _round(attacker: Contingent, defender: Contingent, scenario: Scenario) -> Evaluated:
    fielded = {
        stage.Side.ATTACKER: Fielding.of(attacker, combat=True),
        stage.Side.TARGET: Fielding.of(defender, combat=True),
    }
    held = {
        stage.Side.ATTACKER: _held(scenario.attacker, attacker),
        stage.Side.TARGET: _held(scenario.defender, defender),
    }
    rounds_fought = 0 if scenario.first_round else 1
    return _taken(
        load_program(ROUND, _rules(scenario))
        .built(fielded)
        .evaluate(
            {
                "attacker/standing": fielded[stage.Side.ATTACKER].standing(attacker.models),
                "target/standing": fielded[stage.Side.TARGET].standing(defender.models),
                "attacker/rounds-fought": rounds_fought,
                "target/rounds-fought": rounds_fought,
                "attacker/charges-made": int(scenario.attacker.charged is not None),
                "target/charges-made": int(scenario.defender.charged is not None),
            },
            held,
        )
    )


def _held(side: Side, contingent: Contingent) -> Held:
    worn = {piece.id for piece in contingent.loadout.armour}
    shield = {SHIELD} & worn if side.shield else set()
    return Held({contingent.in_hand().id, *shield})


def _rules(scenario: Scenario) -> dict[str, Rule]:
    return {slug: rule for slug, rule in REPO.rules.items() if slug not in scenario.dropped}


def _taken(lanes: tuple[Evaluated, ...]) -> Evaluated:
    (taken,) = (
        each
        for each in lanes
        if all(each.lane.choices[toggle] for toggle in each.lane.program.toggles.values())
    )
    return taken


def _shot(volley: Evaluated, models: int) -> Outcome:
    (shots,) = volley.at("volley/how-many-shots").read("shots").mass
    removed = volley.at("volley/remove-casualties")
    lost = removed.read("models").map(lambda left: models - left)
    return Outcome(
        attacks=shots,
        unsaved=removed.read("unsaved").expect(lambda unsaved: unsaved) / shots,
        casualties={count: p for count, p in lost.mass.items() if p},
    )


def _struck(fought: Evaluated, attackers: int, models: int) -> Outcome:
    """The attacker's blows in a round, read from its own attack groups.

    The chance an attack goes unsaved is the unsaved wounds expected over the
    attacks expected. The attacks are reported when they are certain, and are
    None when the defender's blows back may fell attackers before they strike.
    The casualties are each side's in the round, of the ``attackers`` and the
    ``models`` it fielded. Each side's Initiative is the first slot its attacks
    land in.

    Returns:
        The attacker's attacks, its unsaved chance per attack, each side's
        casualties and each side's Initiative.
    """
    attacks = [
        fought.at(f"round/initiative-{slot}/attacker/how-many-attacks").read("attacks")
        for slot in INITIATIVES
    ]
    unsaved = sum(
        fought.at(f"round/initiative-{slot}/attacker/attack/{part.id}/ward-saves")
        .read("unsaved")
        .expect(lambda wounds: wounds)
        for slot in INITIATIVES
        for part in fought.built.fielded[stage.Side.ATTACKER].parts
    )
    return Outcome(
        attacks=_certain(attacks),
        unsaved=unsaved / sum(made.expect(lambda n: n) for made in attacks),
        casualties=_lost(fought, stage.Side.TARGET, models),
        attacker_casualties=_lost(fought, stage.Side.ATTACKER, attackers),
        initiative={role: _initiative(fought, side) for role, side in _SIDES.items()},
    )


def _lost(fought: Evaluated, side: stage.Side, models: int) -> dict[int, Probability]:
    left = fought.at(f"round/initiative-1/{side}/remove-casualties").read("models")
    lost = left.map(lambda standing: models - standing)
    return {count: p for count, p in lost.mass.items() if p}


def _initiative(fought: Evaluated, side: stage.Side) -> int:
    return max(
        slot
        for slot in INITIATIVES
        if fought.at(f"round/initiative-{slot}/{side}/how-many-attacks")
        .read("attacks")
        .prob(lambda attacks: attacks > 0)
    )


def _certain(attacks: list[Distribution[int]]) -> int | None:
    counts = [tuple(made.mass) for made in attacks]
    if any(len(count) != 1 for count in counts):
        return None
    return sum(count for (count,) in counts)


def _panicked(volley: Evaluated) -> Panic:
    tested = volley.at("volley/heavy-casualties").read("tested").mass.get(True, 0)
    retreat = volley.at("volley/fall-back-or-flee").read("retreat").mass
    return Panic(
        tested,
        retreat.get(Retreat.HOLDS, 0),
        retreat.get(Retreat.FALLS_BACK_IN_GOOD_ORDER, 0),
        retreat.get(Retreat.FLEES, 0),
        retreat.get(Retreat.DESTROYED, 0),
    )


def _fought(fought: FightResult) -> Outcome:
    return Outcome(
        casualties=_pmf(fought.b_casualties),
        attacker_casualties=_pmf(fought.a_casualties),
        margin={lead: p for lead, p in combat_result(fought).margin.items() if p},
    )


def _break(side: SideBreak) -> Break:
    return Break(side.p_gives_ground, side.p_falls_back, side.p_breaks)


def _pmf(masses: Sequence[Probability]) -> dict[int, Probability]:
    return {count: p for count, p in enumerate(masses) if p}


def _chapter(phase: Phase, dropped: frozenset[str] = frozenset()) -> dict[str, Rule]:
    return {
        rule.name: rule
        for rule in REPO.rules.values()
        if rule.category == phase and rule.effects and rule.id not in dropped
    }


def _reference(ref: Ref) -> RuleRef:
    if ref.slug not in REPO.rules:
        raise ValueError(f"no rule entry is filed as {ref.slug!r}")
    return RuleRef(rule=ref.slug, X=ref.x)


def _kept(refs: Iterable[RuleRef], dropped: frozenset[str]) -> list[RuleRef]:
    return [ref for ref in refs if ref.rule not in dropped]


def _weapon(weapon: Weapon, side: Side) -> Weapon:
    added = [_reference(ref) for ref in side.weapon_rules] if weapon.name == side.weapon else []
    profiles = [
        profile.model_copy(
            update={"special_rules": [*_kept(profile.special_rules, side.dropped), *added]}
        )
        for profile in weapon.profiles
    ]
    return weapon.model_copy(update={"profiles": profiles})


def _movement(side: Side) -> Movement:
    if side.moved and side.charged is not None:
        raise ValueError("a side either moved or charged")
    if side.charged is not None:
        return Movement.charged(Charge(side.charged, ChargeArc.FRONT))
    return Movement.march() if side.moved else Movement.stationary()


def _carried(side: Side, printed: Sequence[RuleRef], equipment: Sequence[str]) -> set[str]:
    in_hand = {*equipment, side.weapon}
    on_weapons = [
        ref
        for weapon in REPO.weapons.values()
        if weapon.name in in_hand
        for profile in weapon.profiles
        for ref in profile.special_rules
    ]
    troop_type = REPO.units[side.unit].rank_and_file.special_rules
    return {ref.rule for ref in [*printed, *troop_type, *on_weapons]}


def _field(side: Side) -> Contingent:
    if side.weapon_rules and side.weapon is None:
        raise ValueError("a weapon rule is added to the weapon in hand; name one")
    datasheet = REPO.units[side.unit]
    troop_type = datasheet.rank_and_file
    printed = [*datasheet.special_rules, *map(_reference, side.rules)]
    equipment = [*datasheet.equipment, *side.equipment]
    uncarried = side.dropped - _carried(side, printed, equipment)
    if uncarried:
        raise ValueError(f"{side.unit} carries no {sorted(uncarried)} to drop")
    unit = datasheet.model_copy(
        update={
            "special_rules": _kept(printed, side.dropped),
            "equipment": equipment,
            "troop_type_profile": troop_type.model_copy(
                update={"special_rules": tuple(_kept(troop_type.special_rules, side.dropped))}
            ),
        }
    )
    data = copy.copy(REPO)
    data.weapons = Registry(
        [_weapon(weapon, side) for weapon in REPO.weapons.values()], kind="weapon"
    )
    fielded = Contingent.field(unit, side.models, data=data, frontage=side.frontage)
    moved = fielded.after(_movement(side))
    return moved.wielding(side.weapon) if side.weapon is not None else moved
