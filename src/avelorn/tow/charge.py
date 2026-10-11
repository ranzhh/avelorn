"""A charge's Charge roll, made on the graph."""

from dataclasses import dataclass
from fractions import Fraction

from avelorn.core.distribution import Probability
from avelorn.tow.contingent import Charge, Contingent
from avelorn.tow.fielding import Fielding
from avelorn.tow.programs import Evaluated, Loaded
from avelorn.tow.schema.side import Side


@dataclass(frozen=True)
class ChargeRoll:
    """The roll of ``move``, in the lane in which every rule the players may decline is taken."""

    move: Charge
    evaluated: Evaluated

    @property
    def reaches(self) -> Probability:
        """The chance the charge range reaches the enemy, ``move.full_inches`` away."""
        program = self.evaluated.lane.program.name
        reached = self.evaluated.at(f"{program}/determine-charge-range").read("reaches")
        return reached.mass.get(True, Fraction(0))


def roll_charge(
    loaded: Loaded, charger: Contingent, target: Contingent, move: Charge
) -> ChargeRoll:
    """Roll the charge range of ``charger``'s charge on ``target``, ``move.full_inches`` away.

    Returns:
        The roll's lane in which every rule the players may decline is taken.
    """
    fielded = {
        Side.ATTACKER: Fielding.of(charger, combat=True),
        Side.TARGET: Fielding.of(target, combat=True),
    }
    lanes = loaded.built(fielded).evaluate({"distance": move.full_inches})
    (taken,) = (evaluated for evaluated in lanes if not evaluated.lane.out)
    return ChargeRoll(move, taken)
