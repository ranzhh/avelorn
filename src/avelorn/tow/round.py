"""A round of close combat, resolved on the graph."""

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from functools import partial
from types import MappingProxyType

from avelorn.core.distribution import Distribution
from avelorn.tow.changes import Uses
from avelorn.tow.contingent import ChargeArc, Contingent
from avelorn.tow.fielding import SHIELD, Fielding, Held
from avelorn.tow.kernels import Standings
from avelorn.tow.programs import Evaluated, Knowns, Loaded
from avelorn.tow.schema.side import Side
from avelorn.tow.steps import WEAPON_CHOICE, BreakTest, Fought
from avelorn.tow.volley import Volley

INITIATIVES = range(10, 0, -1)


@dataclass(frozen=True)
class Fight:
    """A round's lane in which every rule the players may decline is taken.

    ``fielded`` is each side as it was fielded, before a Stand & Shoot thinned it.
    """

    evaluated: Evaluated
    fielded: Mapping[Side, Standings]

    def _read(self, path: str, reading: str) -> Distribution[Hashable]:
        return self.evaluated.at(f"{self.evaluated.lane.program.name}/{path}").read(reading)

    def casualties(self, side: Side) -> Distribution[int]:
        """The models a side has lost once every blow of the round is struck.

        Returns:
            The count lost since the side was fielded.
        """
        left = self._read(f"stomp-attacks/{side}/remove-casualties", "models").map(_count)
        return left.map(lambda standing: self.fielded[side].models - standing)

    def initiative(self, side: Side) -> int:
        """The Initiative a side strikes at: the highest one at which it may make attacks.

        Returns:
            The Initiative.
        """
        return max(
            slot
            for slot in INITIATIVES
            if self._read(f"initiative-{slot}/{side}/how-many-attacks", "attacks")
            .map(_count)
            .prob(lambda attacks: attacks > 0)
        )

    @property
    def first_striker(self) -> Side | None:
        """The side striking at the higher Initiative, or None when both strike at once."""
        attacker, target = self.initiative(Side.ATTACKER), self.initiative(Side.TARGET)
        if attacker == target:
            return None
        return Side.ATTACKER if attacker > target else Side.TARGET

    def fought(self, side: Side) -> Distribution[Fought]:
        """How the round went for a side.

        Returns:
            Won, drawn or lost.
        """
        return self._read(f"{side}/who-is-the-winner", "result").map(_fought)

    def margin(self, side: Side) -> Distribution[int]:
        """A side's combat result less its enemy's.

        Returns:
            The margin.
        """
        return self._read(f"{side}/who-is-the-winner", "margin").map(_count)

    def settled(self, side: Side) -> Distribution[BreakTest]:
        """The Break test result a side acts on; one that did not lose takes none.

        Returns:
            The result.
        """
        return self._read(f"{side}/loser-falls-back-in-good-order", "result").map(_break_test)

    def rank_bonus(self, side: Side) -> int:
        """A side's Rank Bonus as it was fielded.

        Returns:
            The Rank Bonus.
        """
        return self.evaluated.built.fielded[side].rank_bonus(self.fielded[side])

    def unit_strength(self, side: Side) -> int:
        """A side's Unit Strength as it was fielded.

        Returns:
            The Unit Strength.
        """
        return self.evaluated.built.fielded[side].unit_strength(self.fielded[side])

    @property
    def held(self) -> tuple[str, ...]:
        """The rules the round holds without applying: no landing, or held at every one."""
        return self.evaluated.held


def _count(value: Hashable) -> int:
    if not isinstance(value, int):
        raise TypeError(f"{value!r} is no count")
    return value


def _fought(value: Hashable) -> Fought:
    if not isinstance(value, Fought):
        raise TypeError(f"{value!r} is no outcome of a round")
    return value


def _break_test(value: Hashable) -> BreakTest:
    if not isinstance(value, BreakTest):
        raise TypeError(f"{value!r} is no Break test result")
    return value


def _held(side: Contingent) -> Held:
    weapon = side.in_hand()
    barred = {
        effect.bar
        for rule in side.in_hand_rules()
        for effect in rule.effects
        if effect.bar is not None and effect.at is not None and effect.at.step == WEAPON_CHOICE
    }
    worn = {piece.id for piece in side.loadout.armour}
    return Held({weapon.id, *(({SHIELD} & worn) - barred)})


def _thinned(knowns: Mapping[str, Hashable], first_round: bool, standing: Standings) -> Knowns:
    thinned = {"attacker/standing": standing, "attacker/standing-at-start-of-round": standing}
    if not first_round:
        thinned["attacker/standing-at-start-of-turn"] = standing
    return Knowns.of({**knowns, **thinned})


def fight_round(
    loaded: Loaded,
    a: Contingent,
    b: Contingent,
    *,
    first_round: bool,
    stood: Volley | None = None,
) -> Fight:
    """Fight a round of combat between ``a``, the attacker, and ``b``, the target.

    At Step 1.1 each side takes up its weapon in hand, with the shield it
    wears unless that weapon's rules bar it there, as Requires Two Hands does.
    A charge counts only in the first round, the turn it was made; the arc it
    struck counts for the whole combat. ``stood`` is a Stand & Shoot at ``a``:
    the round starts from what it left standing, and the Wounds it caused
    count toward ``b``'s combat result in the first round, the turn it was made.

    Returns:
        The round's lane in which every rule the players may decline is taken.
    """
    sides = {Side.ATTACKER: a, Side.TARGET: b}
    fielded = {side: Fielding.of(each, combat=True) for side, each in sides.items()}
    standing = {side: fielded[side].standing(each.models) for side, each in sides.items()}
    charges = {side: each.movement.charge if first_round else None for side, each in sides.items()}
    knowns: dict[str, Hashable] = {}
    for side, each in sides.items():
        charge, received, made = charges[side], charges[side.other], each.movement.charge
        knowns |= {
            f"{side}/standing": standing[side],
            f"{side}/standing-at-start-of-round": standing[side],
            f"{side}/standing-at-start-of-turn": standing[side],
            f"{side}/rounds-fought": 0 if first_round else 1,
            f"{side}/charges-made": int(charge is not None),
            f"{side}/charge-move": 0 if charge is None else charge.full_inches,
            f"{side}/enemy-arc": ChargeArc.FRONT if made is None else made.arc,
            f"{side}/charges-received": int(received is not None),
            f"{side}/break-tests-taken": 0,
            f"{side}/uses-this-game": Uses(),
        }
    starts = (
        Distribution.pure(Knowns.of(knowns))
        if stood is None
        else stood.standing.map(partial(_thinned, knowns, first_round))
    )
    choices = {side: _held(each) for side, each in sides.items()}
    lanes = loaded.built(fielded).evaluate_from(starts, choices)
    (taken,) = (evaluated for evaluated in lanes if not evaluated.lane.out)
    return Fight(taken, MappingProxyType(standing))
