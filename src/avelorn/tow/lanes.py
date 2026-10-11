"""A round of close combat drawn in two lanes: the charger's above, its target's below.

Time runs left to right: the units, the battlefield between them, the charge
and the reaction it met, the Stand & Shoot fired, each Initiative step in which
a side strikes, the combat result, and each side's Break test. Every figure is
read off the evaluated lane of the round and of the Stand & Shoot before it.
The engine works in rationals; these are floats, and a mean is the expectation
over every outcome.
"""

from collections.abc import Hashable, Iterable, Mapping
from fractions import Fraction
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from avelorn.core.distribution import Distribution
from avelorn.core.graph import Slot, Step, Verdict
from avelorn.tow.contingent import Charge, ChargeArc, Contingent
from avelorn.tow.programs import At, Evaluated
from avelorn.tow.round import Fight
from avelorn.tow.schema.side import Side
from avelorn.tow.schema.unit import OptionKind
from avelorn.tow.steps import AUTOMATIC_HITS, NO_ROLL, WEAPON_CHOICE, BreakTest, Fought, scores
from avelorn.tow.views import ChosenOption, Reacting, by_count
from avelorn.tow.volley import Volley

_ROLLS = ("roll-to-hit", "roll-to-wound", "make-armour-saves", "ward-saves")
_READYING = (WEAPON_CHOICE, "who-can-fight", "who-strikes-first")
_SCORING = ("calculate-combat-result", "who-is-the-winner")


class _Drawn(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PerSide[T](_Drawn):
    """One value for each side: the attacker, which made any charge, and its target."""

    attacker: T
    target: T


class LandedRule(_Drawn):
    """A rule landing on a node's steps, whose it is, and whether it applied in any outcome."""

    name: str
    side: Side
    applied: bool


class Command(_Drawn):
    """The command models a unit bought."""

    champion: bool
    standard: bool
    musician: bool


class LaneUnit(_Drawn):
    """A unit as it is fielded: ``frontage`` files wide and ``ranks`` deep.

    ``options`` are the ones it bought, and ``command`` the command models among
    them, which stand in its front rank. ``rules`` land on the steps it takes
    before anyone strikes: its weapon choice, Who Can Fight, Who Strikes First.
    """

    unit: str
    name: str
    size: int
    options: list[ChosenOption]
    weapon: str
    frontage: int
    ranks: int
    command: Command
    rules: list[LandedRule]


class Battlefield(_Drawn):
    """What lies between the units: the inches the charge covered and the arc it struck."""

    distance: int
    arc: ChargeArc


class LaneCharge(_Drawn):
    """The charge, and the chance its roll reaches; None while the roll is not modelled."""

    distance: int
    arc: ChargeArc
    reaches: float | None
    rules: list[LandedRule]


class Reactions(_Drawn):
    """Which charge reactions the target could declare; Flee is not modelled."""

    hold: bool
    stand_and_shoot: bool
    flee: bool


class LaneReaction(_Drawn):
    """The reaction the target declared, and those it could have."""

    chosen: Reacting
    offered: Reactions


class Needed(_Drawn):
    """The score each roll needs, scores that differ joined with "or".

    "-" is a roll that cannot succeed or is not made, and None a roll the step
    has no place for, as Impact Hits roll no To Hit.
    """

    hit: str | None
    wound: str | None
    save: str | None
    ward: str | None


class LaneVolley(_Drawn):
    """The Stand & Shoot: the shots fired, the scores they need, the mean unsaved wounds.

    The target shoots, so its rules are the target's and the charger's the attacker's.
    """

    shots: int
    needed: Needed
    unsaved: float
    rules: list[LandedRule]


class StrikePart(_Drawn):
    """The models of one profile row striking: how many, their attacks and unsaved wounds."""

    name: str
    models: float
    attacks: float
    unsaved: float
    needed: Needed


class Strike(_Drawn):
    """One side striking at one Initiative step, in that side's lane.

    ``slot`` names the step in the round program and ``label`` prints it.
    At Impact Hits and Stomp Attacks the attacks are the hits.
    """

    slot: str
    label: str
    side: Side
    attacks: float
    needed: Needed
    parts: list[StrikePart]
    unsaved: float
    rules: list[LandedRule]


class StandingAt(_Drawn):
    """A side's models standing: at the start, after the volley, or after a strike.

    ``after`` is None at the start, "volley" after the Stand & Shoot, and the
    slot of the enemy's strike after one. ``distribution[k]`` is the chance
    exactly ``k`` stand.
    """

    after: str | None
    models: float
    distribution: list[float]


class CombatResult(_Drawn):
    """Each side's mean combat result, and the chance of each way the round goes."""

    scores: PerSide[float]
    attacker_wins: float
    draw: float
    target_wins: float
    rules: list[LandedRule]


class LaneBreakTest(_Drawn):
    """A side's Break test: the chance it is taken, and of each outcome over the whole round.

    ``margin`` is the side's mean combat result less its enemy's.
    """

    taken: float
    leadership: str | None
    margin: float
    give_ground: float
    fall_back_in_good_order: float
    break_: float = Field(serialization_alias="break")
    rules: list[LandedRule]


class FightLanes(_Drawn):
    """A round of close combat in two lanes, the attacker's above the target's.

    ``strikes`` run in the order they are struck, Impact Hits first and Stomp
    Attacks last, and a step in which nobody strikes is left out. The
    battlefield, the charge and the reaction are None for a fight with no
    charge, and the volley for one met with a Hold. ``not_modelled`` names the
    rules held without applying.
    """

    units: PerSide[LaneUnit]
    battlefield: Battlefield | None
    charge: LaneCharge | None
    reaction: LaneReaction | None
    volley: LaneVolley | None
    strikes: list[Strike]
    standing: PerSide[list[StandingAt]]
    result: CombatResult
    breaks: PerSide[LaneBreakTest]
    not_modelled: list[str]

    @classmethod
    def of(
        cls, sides: Mapping[Side, Contingent], fight: Fight, stood: Volley | None
    ) -> "FightLanes":
        """Draw a round fought between ``sides``, after the Stand & Shoot ``stood``.

        Returns:
            The lanes.
        """
        charge = sides[Side.ATTACKER].movement.charge
        struck = (_strike(fight, slot, side) for slot in _slots(fight) for side in Side)
        strikes = [strike for strike in struck if strike is not None]
        return cls(
            units=PerSide(
                attacker=_unit(fight, sides[Side.ATTACKER], Side.ATTACKER),
                target=_unit(fight, sides[Side.TARGET], Side.TARGET),
            ),
            battlefield=None
            if charge is None
            else Battlefield(distance=charge.full_inches, arc=charge.arc),
            charge=None if charge is None else _charge(fight, charge),
            reaction=None if charge is None else _reaction(sides[Side.TARGET], stood),
            volley=None if stood is None else _volley(stood),
            strikes=strikes,
            standing=PerSide(
                attacker=_standing(fight, Side.ATTACKER, strikes, stood),
                target=_standing(fight, Side.TARGET, strikes, None),
            ),
            result=_result(fight),
            breaks=PerSide(
                attacker=_break(fight, Side.ATTACKER), target=_break(fight, Side.TARGET)
            ),
            not_modelled=_not_modelled(
                fight.evaluated, *(() if stood is None else (stood.evaluated,))
            ),
        )


def _at(fight: Fight, path: str) -> At:
    return fight.evaluated.at(f"{fight.evaluated.lane.program.name}/{path}")


def _rules(fight: Fight, *paths: str) -> list[LandedRule]:
    return _landed(fight.evaluated, [_at(fight, path).step for path in paths])


def _mean(distribution: Distribution[Any]) -> float:
    return float(distribution.expect(Fraction))


def _each(reading: Distribution[Any], fighter: str) -> Distribution[int]:
    return reading.map(lambda counted: counted.of(fighter))


def _landed(evaluated: Evaluated, steps: Iterable[Step[Any]]) -> list[LandedRule]:
    lane = evaluated.lane
    on = set(steps)
    landed = []
    for node in lane.program.rules.values():
        at = [landing.at for landing in node.landings if landing.at in on]
        if at:
            applied = any(lane.verdicts(node.id, step).mass.get(Verdict.APPLIED, 0) for step in at)
            landed.append(LandedRule(name=node.name, side=Side(node.holder.side), applied=applied))
    return landed


def _unit(fight: Fight, contingent: Contingent, side: Side) -> LaneUnit:
    unit = contingent.unit
    chosen = [option for option in unit.options if option.id in contingent.options]
    kinds = {option.kind for option in chosen}
    return LaneUnit(
        unit=unit.id,
        name=unit.name,
        size=contingent.models,
        options=[ChosenOption(id=option.id, name=option.name) for option in chosen],
        weapon=contingent.in_hand().name,
        frontage=contingent.formation.files,
        ranks=contingent.formation.ranks,
        command=Command(
            champion=OptionKind.CHAMPION in kinds,
            standard=OptionKind.STANDARD_BEARER in kinds,
            musician=OptionKind.MUSICIAN in kinds,
        ),
        rules=_rules(fight, *(f"{side}/{step}" for step in _READYING)),
    )


def _charge(fight: Fight, charge: Charge) -> LaneCharge:
    return LaneCharge(
        distance=charge.full_inches,
        arc=charge.arc,
        reaches=None,
        rules=_rules(fight, "attacker/the-charge-move"),
    )


def _reaction(target: Contingent, stood: Volley | None) -> LaneReaction:
    shoots = any(weapon.missile_profile is not None for weapon in target.loadout.weapons)
    return LaneReaction(
        chosen="hold" if stood is None else "stand-and-shoot",
        offered=Reactions(hold=True, stand_and_shoot=shoots, flee=False),
    )


def _volley(stood: Volley) -> LaneVolley:
    return LaneVolley(
        shots=stood.shots,
        needed=Needed(
            hit=stood.needed("roll-to-hit"),
            wound=stood.needed("roll-to-wound"),
            save=stood.needed("make-armour-saves"),
            ward=stood.needed("ward-saves"),
        ),
        unsaved=_mean(stood.unsaved),
        rules=[
            rule.model_copy(update={"side": rule.side.other})
            for rule in _landed(stood.evaluated, stood.evaluated.lane.program.steps)
        ],
    )


def _slots(fight: Fight) -> list[str]:
    return [block.name for block in fight.evaluated.lane.program.blocks if isinstance(block, Slot)]


def _strike(fight: Fight, slot: str, side: Side) -> Strike | None:
    automatic = slot in AUTOMATIC_HITS
    counter = f"{slot}/{side}/{slot if automatic else 'how-many-attacks'}"
    count = _at(fight, counter).read("hits" if automatic else "attacks")
    if not count.prob(lambda struck: struck > 0):
        return None
    made = _at(fight, counter).read("parts")
    fighting = _at(fight, counter).read("fighting")
    rows: dict[str, list[str]] = {}
    for fighter in fight.evaluated.built.fielded[side].fighters:
        if _each(made, fighter.id).prob(lambda attacks: attacks > 0):
            rows.setdefault(fighter.row.name, []).append(fighter.id)
    group = f"{slot}/{side}/attack"
    parts = [
        StrikePart(
            name=name,
            models=sum(_mean(_each(fighting, fighter)) for fighter in row),
            attacks=sum(_mean(_each(made, fighter)) for fighter in row),
            unsaved=sum(_unsaved(fight, f"{group}/{fighter}") for fighter in row),
            needed=_needed(fight, [f"{group}/{fighter}" for fighter in row], automatic),
        )
        for name, row in rows.items()
    ]
    attacking = [f"{group}/{fighter}" for row in rows.values() for fighter in row]
    rolls = _ROLLS[1:] if automatic else _ROLLS
    return Strike(
        slot=slot,
        label=slot.replace("-", " ").title(),
        side=side,
        attacks=_mean(count),
        needed=_needed(fight, attacking, automatic),
        parts=parts,
        unsaved=sum(part.unsaved for part in parts),
        rules=_rules(
            fight,
            counter,
            *(f"{attack}/{roll}" for attack in attacking for roll in rolls),
            f"{slot}/{side.other}/remove-casualties",
        ),
    )


def _unsaved(fight: Fight, attack: str) -> float:
    return _mean(_at(fight, f"{attack}/ward-saves").read("unsaved"))


def _needed(fight: Fight, attacking: list[str], automatic: bool) -> Needed:
    def needed(roll: str) -> str | None:
        return scores(_at(fight, f"{attack}/{roll}").read("needed") for attack in attacking)

    return Needed(
        hit=None if automatic else needed("roll-to-hit"),
        wound=needed("roll-to-wound"),
        save=needed("make-armour-saves"),
        ward=needed("ward-saves"),
    )


def _standing(
    fight: Fight, side: Side, strikes: list[Strike], stood: Volley | None
) -> list[StandingAt]:
    size = fight.fielded[side].models
    standing = [_stand(None, Distribution.pure(size))]
    if stood is not None:
        standing.append(_stand("volley", stood.casualties.map(lambda lost: size - lost)))
    standing.extend(
        _stand(strike.slot, _at(fight, f"{strike.slot}/{side}/remove-casualties").read("models"))
        for strike in strikes
        if strike.side is side.other
    )
    return standing


def _stand(after: str | None, models: Distribution[int]) -> StandingAt:
    return StandingAt(after=after, models=_mean(models), distribution=by_count(models))


def _result(fight: Fight) -> CombatResult:
    fought = fight.fought(Side.ATTACKER).mass
    return CombatResult(
        scores=PerSide(
            attacker=_mean(_at(fight, "attacker/calculate-combat-result").read("score")),
            target=_mean(_at(fight, "target/calculate-combat-result").read("score")),
        ),
        attacker_wins=float(fought.get(Fought.WON, 0)),
        draw=float(fought.get(Fought.DRAWN, 0)),
        target_wins=float(fought.get(Fought.LOST, 0)),
        rules=_rules(fight, *(f"{side}/{step}" for side in Side for step in _SCORING)),
    )


def _break(fight: Fight, side: Side) -> LaneBreakTest:
    test = _at(fight, f"{side}/break-test")
    settled = fight.settled(side).mass
    return LaneBreakTest(
        taken=float(test.read("test").prob(lambda result: result is not BreakTest.NOT_TAKEN)),
        leadership=_leadership(test.read("needed")),
        margin=_mean(fight.margin(side)),
        give_ground=float(settled.get(BreakTest.GIVES_GROUND, 0)),
        fall_back_in_good_order=float(settled.get(BreakTest.FALLS_BACK_IN_GOOD_ORDER, 0)),
        break_=float(settled.get(BreakTest.BREAKS, 0)),
        rules=_rules(fight, f"{side}/break-test", f"{side}/loser-falls-back-in-good-order"),
    )


def _leadership(needed: Distribution[Hashable]) -> str | None:
    shown = sorted({str(value) for value, p in needed.mass.items() if p and value != NO_ROLL})
    return " or ".join(shown) or None


def _not_modelled(*evaluated: Evaluated) -> list[str]:
    held = set[str]().union(*(each.held for each in evaluated))
    return sorted(name for name in held if all(_held(each, name) for each in evaluated))


def _held(evaluated: Evaluated, name: str) -> bool:
    attached = {node.name for node in evaluated.lane.program.rules.values()}
    return name in evaluated.held or name not in attached
