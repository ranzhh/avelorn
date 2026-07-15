"""Characteristic tests: roll-equal-or-under against a profile value.

Sources (tow.whfb.app): model-profiles/characteristic-tests,
model-profiles/leadership-tests. The rulebook splits testing in two:

- A characteristic test rolls one D6 against the characteristic; a
  natural 6 is always a failure and a natural 1 always a success,
  regardless of modifiers, and a characteristic of 0 or "-"
  automatically fails.
- A Leadership test rolls 2D6, passing on equal-or-under; a natural 12
  (double 6) is always a fail and a natural 2 (double 1) always a pass,
  regardless of modifiers.

One function matches on the characteristic, mirroring that split; the
exactness discipline is the attack walk's — probabilities are counts
over the enumerated outcomes.
"""

import logging
from fractions import Fraction
from itertools import product

from avelorn.tow.schema.unit import Characteristic, Unit

logger = logging.getLogger(__name__)


def pass_probability(characteristic: Characteristic, value: int | None) -> Fraction:
    """Exact probability that a test against a characteristic passes.

    A value of None ("-") or 0 fails automatically — printed for
    characteristic tests, and applied to Leadership the same way as the
    conservative reading.

    Returns:
        P(pass) under the procedure the rulebook assigns to the
        characteristic: 2D6 roll-under for Leadership, one D6 for all
        others, each with its printed natural bounds.
    """
    if value is None or value <= 0:
        return Fraction(0)
    match characteristic:
        case Characteristic.LEADERSHIP:
            passes = sum(
                1
                for first, second in product(range(1, 7), repeat=2)
                if (roll := first + second) == 2 or (roll != 12 and roll <= value)
            )
            p = Fraction(passes, 36)
        case _:
            passes = sum(1 for roll in range(1, 7) if roll == 1 or (roll != 6 and roll <= value))
            p = Fraction(passes, 6)
    logger.debug("%s test vs %s -> p=%s = %.3f", characteristic.name, value, p, float(p))
    return p


def unit_pass_probability(unit: Unit, characteristic: Characteristic) -> Fraction:
    """A unit's test probability, against its highest value.

    Returns:
        P(pass) for the unit, per the printed use-the-highest rule.
    """
    return pass_probability(characteristic, unit.highest(characteristic))
