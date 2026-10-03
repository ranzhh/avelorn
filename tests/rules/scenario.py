"""A fight fielded from data/ and resolved; only :func:`resolve` knows which engine answers."""

import copy
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from avelorn.core.distribution import Probability
from avelorn.core.registry import Registry
from avelorn.tow.contingent import Charge, ChargeArc, Contingent, Movement
from avelorn.tow.data import TOWRepository
from avelorn.tow.phases.combat import (
    CombatPhase,
    FightResult,
    SideBreak,
    break_test,
    combat_result,
    fight,
    strike_unit,
)
from avelorn.tow.phases.movement import StandAndShoot, charge
from avelorn.tow.phases.shooting import make_panic_tests, shoot_unit
from avelorn.tow.schema.phase import Phase
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.weapon import Weapon

REPO = TOWRepository()

CHAPTERS = (Phase.SHOOTING, Phase.COMBAT)


class Kind(StrEnum):
    """What the attacker does; STRIKE is the attacker's attacks alone, with no blows back."""

    SHOOT = "shoot"
    STRIKE = "strike"
    FIGHT = "fight"
    STAND_AND_SHOOT = "charge-with-stand-and-shoot"
    PANIC = "panic"
    BREAK = "break"


ROUNDS = frozenset({Kind.FIGHT, Kind.BREAK})


class Role(StrEnum):
    ATTACKER = "attacker"
    DEFENDER = "defender"


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
    """A datasheet fielded at ``models``; ``charged`` is the inches of a front-arc charge."""

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


@dataclass(frozen=True)
class Scenario:
    """Two sides and what the attacker does; in a Stand & Shoot the defender fires."""

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
    first: Role | None = None
    margin: Mapping[int, Probability] = field(default_factory=dict)
    breaks: Mapping[Role, Break] = field(default_factory=dict)
    panic: Panic | None = None


def resolve(scenario: Scenario) -> Outcome:
    """Resolve ``scenario`` on the legacy engine.

    Returns:
        The outcome its kind decides.

    Raises:
        ValueError: a round with no ``first_round``, another kind with one, a Stand &
            Shoot whose attacker did not charge, or a dropped chapter rule that is
            not one.
    """
    if (scenario.kind in ROUNDS) != (scenario.first_round is not None):
        raise ValueError(f"first_round is an input of a fight or break, not of {scenario.kind}")
    unknown = scenario.dropped - {
        rule.id for phase in CHAPTERS for rule in _chapter(phase).values()
    }
    if unknown:
        raise ValueError(f"not a chapter rule with effects: {sorted(unknown)}")
    attacker, defender = _field(scenario.attacker), _field(scenario.defender)
    shooting = _chapter(Phase.SHOOTING, scenario.dropped)
    combat = _chapter(Phase.COMBAT, scenario.dropped)
    match scenario.kind:
        case Kind.SHOOT | Kind.PANIC:
            volley = shoot_unit(
                attacker, defender, phase_rules=shooting, distance=scenario.distance
            )
            outcome = Outcome(
                attacks=volley.shots,
                unsaved=volley.p_unsaved,
                casualties=_pmf(volley.casualties),
            )
            if scenario.kind is Kind.SHOOT:
                return outcome
            panic = make_panic_tests(volley, defender)
            return replace(
                outcome,
                panic=Panic(
                    panic.p_test,
                    panic.p_holds,
                    panic.p_falls_back,
                    panic.p_flees,
                    panic.p_destroyed,
                ),
            )
        case Kind.STRIKE:
            struck = strike_unit(attacker, defender)
            return Outcome(
                attacks=struck.attacks,
                unsaved=struck.p_unsaved,
                casualties=_pmf(struck.casualties),
            )
        case Kind.FIGHT | Kind.BREAK:
            fought = fight(
                attacker, defender, first_round=scenario.first_round, phase_rules=combat
            )
            outcome = _fought(fought, attacker)
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
            return replace(_fought(fought, engagement.a), attacks=reaction.shots)


def _fought(fought: FightResult, attacker: Contingent) -> Outcome:
    first = None
    if fought.first_striker is not None:
        first = Role.ATTACKER if fought.first_striker is attacker else Role.DEFENDER
    return Outcome(
        casualties=_pmf(fought.b_casualties),
        attacker_casualties=_pmf(fought.a_casualties),
        initiative={
            Role.ATTACKER: fought.a_initiative.value,
            Role.DEFENDER: fought.b_initiative.value,
        },
        first=first,
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
