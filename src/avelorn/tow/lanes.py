"""A round of close combat drawn in two lanes: the charger's above, its target's below.

Time runs left to right: the units, the battlefield between them, the charge
and the reaction it met, the Stand & Shoot fired, each Initiative step in which
a side strikes, the combat result, and each side's Break test. Every figure is
read off the evaluated lane of the Charge roll, of the Stand & Shoot and of the
round. The engine works in rationals; these are floats, and a count that varies
is drawn as its spread over every outcome.
"""

from collections.abc import Hashable, Iterable, Mapping
from fractions import Fraction
from math import sqrt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from avelorn.core.distribution import Distribution
from avelorn.core.graph import Slot, Step, Verdict
from avelorn.tow.charge import ChargeRoll
from avelorn.tow.contingent import ChargeArc, Contingent
from avelorn.tow.fielding import Part
from avelorn.tow.programs import At, Evaluated, held_throughout
from avelorn.tow.round import Fight
from avelorn.tow.schema.side import Side
from avelorn.tow.schema.unit import OptionKind
from avelorn.tow.steps import AUTOMATIC_HITS, NO_ROLL, WEAPON_CHOICE, BreakTest, Fought, scores
from avelorn.tow.views import ChosenOption, Reacting
from avelorn.tow.volley import Volley

_ROLLS = ("roll-to-hit", "roll-to-wound", "make-armour-saves", "ward-saves")
_READYING = (WEAPON_CHOICE, "who-can-fight", "who-strikes-first")
_SCORING = ("calculate-combat-result", "who-is-the-winner")
_COMMAND = (OptionKind.CHAMPION, OptionKind.STANDARD_BEARER, OptionKind.MUSICIAN)


class _Drawn(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Spread(_Drawn):
    """A count over every way things go: its mean, its standard deviation, and its chances.

    ``distribution[k]`` is the chance the count is ``least + k``, and ``least``
    is 0 unless the count can fall below it.
    """

    mean: float
    sd: float
    least: int
    distribution: list[float]

    @classmethod
    def of(cls, counted: Distribution[Any]) -> "Spread":
        """Spread a count's distribution.

        Returns:
            Its mean, standard deviation and chances.
        """
        mean = counted.expect(Fraction)
        variance = counted.expect(lambda count: (count - mean) ** 2)
        reached = [count for count, p in counted.mass.items() if p]
        least = min(0, *reached)
        return cls(
            mean=float(mean),
            sd=sqrt(variance),
            least=least,
            distribution=[
                float(counted.mass.get(count, 0)) for count in range(least, max(reached) + 1)
            ],
        )


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
    """A command model a unit bought, by its kind and its printed name."""

    kind: Literal[OptionKind.CHAMPION, OptionKind.STANDARD_BEARER, OptionKind.MUSICIAN]
    name: str


class LaneUnit(_Drawn):
    """A unit as it is fielded: ``frontage`` files wide and ``ranks`` deep.

    ``options`` are the ones it bought besides its command models, which
    ``command`` gives and which stand in its front rank. ``held`` names what it
    took up at its weapon choice: the weapon in hand, and the shield when it
    uses one. ``rules`` land on the steps it takes before anyone strikes: its
    weapon choice, Who Can Fight, Who Strikes First.
    """

    unit: str
    name: str
    size: int
    options: list[ChosenOption]
    held: list[str]
    frontage: int
    ranks: int
    command: list[Command]
    rules: list[LandedRule]


class Battlefield(_Drawn):
    """What lies between the units: the inches the charge covered and the arc it struck."""

    distance: int
    arc: ChargeArc


class Term(_Drawn):
    """One term of a sum of inches, and its name: a characteristic's, a rule's, or none."""

    name: str | None
    inches: int


class LaneCharge(_Drawn):
    """The charge, the range its Charge roll gives, and the chance it reaches the target.

    The target stands ``distance`` away. ``maximum`` is the maximum possible
    charge range term by term, and ``furthest`` the furthest the dice reach
    within it.
    """

    distance: int
    arc: ChargeArc
    reaches: float
    range: Spread
    maximum: list[Term]
    furthest: int
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


class VolleyPart(_Drawn):
    """The models of one profile row shooting: their shots and the wounds they leave unsaved."""

    name: str
    shots: int
    unsaved: Spread


class LaneVolley(_Drawn):
    """The Stand & Shoot: the shots fired, the scores they need, and the chargers it fells.

    The target shoots, so its rules are the target's and the charger's the attacker's.
    """

    shots: int
    needed: Needed
    casualties: Spread
    parts: list[VolleyPart]
    rules: list[LandedRule]


class StrikePart(_Drawn):
    """The models of one profile row striking: how many, their attacks and unsaved wounds."""

    name: str
    models: Spread
    attacks: Spread
    unsaved: Spread
    needed: Needed


class Strike(_Drawn):
    """One side striking at one Initiative step, in that side's lane.

    ``slot`` names the step in the round program and ``label`` prints it.
    At Impact Hits and Stomp Attacks the attacks are the hits.
    """

    slot: str
    label: str
    side: Side
    attacks: Spread
    needed: Needed
    parts: list[StrikePart]
    unsaved: Spread
    rules: list[LandedRule]


class StandingAt(_Drawn):
    """A side's models standing: at the start, after the volley, or after a strike.

    ``after`` is None at the start, "volley" after the Stand & Shoot, and the
    slot of the enemy's strike after one.
    """

    after: str | None
    models: Spread


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
    charge, and the volley for one met with a Hold. The round is fought only
    when the charge reaches, so every figure from the strikes on is
    conditional on it reaching. ``not_modelled`` names the rules held without
    applying.
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
        cls,
        sides: Mapping[Side, Contingent],
        fight: Fight,
        rolled: ChargeRoll | None,
        stood: Volley | None,
    ) -> "FightLanes":
        """Draw a round fought between ``sides``, after the charge ``rolled`` and its reaction.

        ``stood`` is the Stand & Shoot the target reacted with.

        Returns:
            The lanes.
        """
        struck = (_strike(fight, slot, side) for slot in _slots(fight) for side in Side)
        strikes = [strike for strike in struck if strike is not None]
        return cls(
            units=PerSide(
                attacker=_unit(fight, sides[Side.ATTACKER], Side.ATTACKER),
                target=_unit(fight, sides[Side.TARGET], Side.TARGET),
            ),
            battlefield=None
            if rolled is None
            else Battlefield(distance=rolled.move.full_inches, arc=rolled.move.arc),
            charge=None if rolled is None else _charge(fight, rolled),
            reaction=None if rolled is None else _reaction(sides[Side.TARGET], stood),
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
            not_modelled=held_throughout(
                fight.evaluated,
                *(() if rolled is None else (rolled.evaluated,)),
                *(() if stood is None else (stood.evaluated,)),
            ),
        )


def _at(evaluated: Evaluated, path: str) -> At:
    return evaluated.at(f"{evaluated.lane.program.name}/{path}")


def _rules(fight: Fight, *paths: str) -> list[LandedRule]:
    return _landed(fight.evaluated, [_at(fight.evaluated, path).step for path in paths])


def _mean(distribution: Distribution[Any]) -> float:
    return float(distribution.expect(Fraction))


def _each(reading: Distribution[Any], fighter: str) -> Distribution[int]:
    return reading.map(lambda counted: counted.of(fighter))


def _summed(reading: Distribution[Any], fighters: list[str]) -> Spread:
    return Spread.of(reading.map(lambda counted: sum(counted.of(each) for each in fighters)))


def _rows(fighters: Iterable[Part], made: Distribution[Any]) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for fighter in fighters:
        if _each(made, fighter.id).prob(lambda count: count > 0):
            rows.setdefault(fighter.row.name, []).append(fighter.id)
    return rows


def _named(evaluated: Evaluated, side: Side) -> dict[str, str]:
    nodes = evaluated.lane.program.rules.values()
    return {node.rule: node.name for node in nodes if node.holder.side == side}


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
    return LaneUnit(
        unit=unit.id,
        name=unit.name,
        size=contingent.models,
        options=[
            ChosenOption(id=option.id, name=option.name)
            for option in chosen
            if option.kind not in _COMMAND
        ],
        held=_holding(fight, contingent, side),
        frontage=contingent.formation.files,
        ranks=contingent.formation.ranks,
        command=[
            Command(kind=kind, name=option.name)
            for kind in _COMMAND
            for option in chosen
            if option.kind is kind
        ],
        rules=_rules(fight, *(f"{side}/{step}" for step in _READYING)),
    )


def _holding(fight: Fight, contingent: Contingent, side: Side) -> list[str]:
    (taken,) = _at(fight.evaluated, f"{side}/{WEAPON_CHOICE}").read("taken").mass
    loadout = contingent.loadout
    names = {piece.id: piece.name for piece in (*loadout.weapons, *loadout.armour)}
    return [names[slug] for slug in taken.option.slugs]


def _charge(fight: Fight, rolled: ChargeRoll) -> LaneCharge:
    roll = rolled.evaluated
    determined = _at(roll, "determine-charge-range")
    ranged = determined.read("range")
    (maximum,) = determined.read("maximum").mass
    named = _named(roll, Side.ATTACKER)
    return LaneCharge(
        distance=rolled.move.full_inches,
        arc=rolled.move.arc,
        reaches=float(rolled.reaches),
        range=Spread.of(ranged),
        maximum=[
            Term(name="Movement", inches=maximum.movement),
            Term(name=None, inches=maximum.printed),
            *(Term(name=named[rule], inches=inches) for rule, inches in maximum.added),
        ],
        furthest=max(inches for inches, p in ranged.mass.items() if p),
        rules=[
            *_landed(roll, roll.lane.program.steps),
            *_rules(fight, "attacker/the-charge-move"),
        ],
    )


def _reaction(target: Contingent, stood: Volley | None) -> LaneReaction:
    shoots = any(weapon.missile_profile is not None for weapon in target.loadout.weapons)
    return LaneReaction(
        chosen="hold" if stood is None else "stand-and-shoot",
        offered=Reactions(hold=True, stand_and_shoot=shoots, flee=False),
    )


def _volley(stood: Volley) -> LaneVolley:
    shot = _at(stood.evaluated, "how-many-shots").read("parts")
    caused = _at(stood.evaluated, "remove-casualties").read("parts")
    (fired,) = shot.mass
    return LaneVolley(
        shots=stood.shots,
        needed=Needed(
            hit=stood.needed("roll-to-hit"),
            wound=stood.needed("roll-to-wound"),
            save=stood.needed("make-armour-saves"),
            ward=stood.needed("ward-saves"),
        ),
        casualties=Spread.of(stood.casualties),
        parts=[
            VolleyPart(
                name=name,
                shots=sum(fired.of(fighter) for fighter in row),
                unsaved=_summed(caused, row),
            )
            for name, row in _rows(stood.shooter.fighters, shot).items()
        ],
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
    count = _at(fight.evaluated, counter).read("hits" if automatic else "attacks")
    if not count.prob(lambda struck: struck > 0):
        return None
    made = _at(fight.evaluated, counter).read("parts")
    fighting = _at(fight.evaluated, counter).read("fighting")
    removed = _at(fight.evaluated, f"{slot}/{side.other}/remove-casualties")
    caused = removed.read("parts")
    rows = _rows(fight.evaluated.built.fielded[side].fighters, made)
    group = f"{slot}/{side}/attack"
    parts = [
        StrikePart(
            name=name,
            models=_summed(fighting, row),
            attacks=_summed(made, row),
            unsaved=_summed(caused, row),
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
        attacks=Spread.of(count),
        needed=_needed(fight, attacking, automatic),
        parts=parts,
        unsaved=Spread.of(removed.read("unsaved")),
        rules=_rules(
            fight,
            counter,
            *(f"{attack}/{roll}" for attack in attacking for roll in rolls),
            f"{slot}/{side.other}/remove-casualties",
        ),
    )


def _needed(fight: Fight, attacking: list[str], automatic: bool) -> Needed:
    def needed(roll: str) -> str | None:
        return scores(
            _at(fight.evaluated, f"{attack}/{roll}").read("needed") for attack in attacking
        )

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
        _stand(
            strike.slot,
            _at(fight.evaluated, f"{strike.slot}/{side}/remove-casualties").read("models"),
        )
        for strike in strikes
        if strike.side is side.other
    )
    return standing


def _stand(after: str | None, models: Distribution[int]) -> StandingAt:
    return StandingAt(after=after, models=Spread.of(models))


def _result(fight: Fight) -> CombatResult:
    fought = fight.fought(Side.ATTACKER).mass
    return CombatResult(
        scores=PerSide(
            attacker=_mean(_at(fight.evaluated, "attacker/calculate-combat-result").read("score")),
            target=_mean(_at(fight.evaluated, "target/calculate-combat-result").read("score")),
        ),
        attacker_wins=float(fought.get(Fought.WON, 0)),
        draw=float(fought.get(Fought.DRAWN, 0)),
        target_wins=float(fought.get(Fought.LOST, 0)),
        rules=_rules(fight, *(f"{side}/{step}" for side in Side for step in _SCORING)),
    )


def _break(fight: Fight, side: Side) -> LaneBreakTest:
    test = _at(fight.evaluated, f"{side}/break-test")
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
