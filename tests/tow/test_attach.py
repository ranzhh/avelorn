"""Rule sources and attaching."""

from avelorn.core.graph import Carrier, Source
from avelorn.tow.contingent import Contingent
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.steps import Fielded

REPO = TOWRepository()


def test_a_side_carries_the_rules_of_the_profile_it_shoots_with() -> None:
    maneaters = Contingent.deploy("maneaters", 2, ["Brace of Ogre Pistols"], data=REPO)
    fielded = Fielded.of(maneaters, "Brace of Ogre Pistols")
    ranged = Source(Carrier.WEAPON, "brace-of-ogre-pistols", "Ranged")

    assert [pair for pair in fielded.sources() if pair[1].carrier is Carrier.WEAPON] == [
        (RuleRef(rule="armour-bane", X=1), ranged),
        (RuleRef(rule="multiple-shots", X=2), ranged),
        (RuleRef(rule="quick-shot"), ranged),
    ]
