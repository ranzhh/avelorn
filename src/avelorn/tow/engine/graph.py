"""What the phases build their graphs from: node kinds, and where a rule's effects go.

A rule enters a graph as a source node carrying a :class:`Bearing`: the rule,
the side that bears it, and whether it came from the unit's datasheet, from
the weapon in use or from the chapter rules. Each effect says where it lands
(:meth:`~avelorn.tow.schema.rule.GatedEffect.lands`); the table here maps
those landings to the nodes this graph builds. A consumer node takes the rule
nodes routed to it as inputs, so the edges are the modelling: a rule node
with no edge out of it is a rule nothing applied.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import NamedTuple

from avelorn.tow.schema.rule import Landing, Rule, Seam
from avelorn.tow.schema.stage import Side, Stage


class Kind(StrEnum):
    UNIT = "unit"
    WEAPON = "weapon"
    CONDITION = "condition"
    RULE = "rule"
    RULES = "rules"
    READ = "read"
    STAGE = "stage"
    WALK = "walk"
    COUNT = "count"
    FOLD = "fold"
    TEST = "test"
    EFFECTIVE = "effective"


class Namespace(StrEnum):
    UNIT = "unit"
    WEAPON = "weapon"
    CORE = "core"


class Bearing(NamedTuple):
    rule: Rule
    side: Side
    origin: Namespace
    grants: Mapping[str, Rule]


SHOTS = "shots"
MULTIPLE_WOUNDS = "multiple-wounds"
MARKS = "attack-marks"

_CONSUMERS: Mapping[Landing, str] = {
    **{Landing(stage.rolled_by, stage): stage.value for stage in Stage},
    Landing(Side.TARGET, Seam.ARMOUR): Stage.MAKE_ARMOUR_SAVES.value,
    Landing(Side.TARGET, Seam.WARD): Stage.WARD_SAVES.value,
    Landing(Side.ATTACKER, Seam.SHOTS): SHOTS,
    Landing(Side.ATTACKER, Seam.CASUALTIES): MULTIPLE_WOUNDS,
    Landing(Side.ATTACKER, Seam.MARKS): MARKS,
}


def routes(bearing: Bearing) -> frozenset[str]:
    landings = bearing.rule.lands(bearing.side, bearing.grants)
    return frozenset(_CONSUMERS[landing] for landing in landings if landing in _CONSUMERS)
