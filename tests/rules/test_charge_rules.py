"""Each rule that changes the Charge roll, rolled with and without it."""

from fractions import Fraction

import pytest
from oracle.procedure import charge_reaches

from rules.scenario import Kind, Role, Scenario, Side, resolve

PRINCES = Side("dragon-princes", 5)
DWARFS = Side("dwarf-warriors", 10)


@pytest.mark.parametrize(
    ("inches", "printed", "plain"),
    [
        pytest.param(14, Fraction(31, 36), Fraction(11, 36), id="needs-a-6"),
        pytest.param(17, Fraction(5, 12), Fraction(0), id="at-the-raised-maximum"),
        pytest.param(18, Fraction(0), Fraction(0), id="past-the-raised-maximum"),
    ],
)
def test_swiftstride(inches: int, printed: Fraction, plain: Fraction) -> None:
    """Dragon Princes add a D6 to the higher of two D6, and charge 3in further at most.

    Their steeds move 8. At 14in the roll needs a 6: a 6 on either die, 1 - (5/6)^2,
    or with the D6 a total of 6, 186 of 216. At 17in the D6 brings the 9 needed
    within the raised maximum of 8 + 9; 18in is past it.
    """
    scenario = Scenario(Kind.CHARGE, PRINCES, DWARFS, distance=inches)
    engine = (
        resolve(scenario).reaches,
        resolve(scenario.without("swiftstride", Role.ATTACKER)).reaches,
    )
    oracle = (charge_reaches(8, inches, swiftstride=True), charge_reaches(8, inches))
    assert engine == oracle == (printed, plain)
