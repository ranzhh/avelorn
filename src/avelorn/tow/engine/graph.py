"""What the phases build their graphs from: node kinds, and where a rule's effects go.

A rule enters a graph as a source node carrying a :class:`Bearing`: the rule,
the side that bears it, and whether it came from the unit's datasheet, from
the weapon in use or from the chapter rules. :func:`routes` reads the rule's
effects and names the consumer nodes they belong to, using the compiler's own
table of which side owns each roll quantity. A consumer node takes the rule
nodes routed to it as inputs, so the edges are the modelling: a rule node
with no edge out of it is a rule nothing applied.
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import NamedTuple

from avelorn.tow.engine.rules import ROLLS
from avelorn.tow.schema.rule import (
    AttackMarkEffect,
    BarEffect,
    BlowEffect,
    GrantEffect,
    ModifierEffect,
    Quantity,
    RerollEffect,
    Rule,
    RuleEffect,
    Seam,
    VolleyEffect,
    WoundMultiplierEffect,
)
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


def routes(bearing: Bearing) -> frozenset[str]:
    found: set[str] = set()
    for effect in bearing.rule.effects:
        found |= _routes(effect, bearing)
    return frozenset(found)


def _routes(effect: RuleEffect, bearing: Bearing) -> set[str]:
    side, origin = bearing.side, bearing.origin
    if isinstance(effect, ModifierEffect):
        found: set[str] = set()
        for key in (*(effect.add or {}), *(effect.set_ or {})):
            if isinstance(key, Quantity) and key.seam is Seam.ROLL:
                roll = ROLLS[key]
                owner = roll.side.other if effect.enemy else roll.side
                if owner is side:
                    found.add(roll.stage.value)
            elif isinstance(key, Quantity) and side is Side.TARGET and not effect.enemy:
                if key.seam is Seam.ARMOUR:
                    found.add(Stage.MAKE_ARMOUR_SAVES.value)
                elif key.seam is Seam.WARD:
                    found.add(Stage.WARD_SAVES.value)
        return found
    if isinstance(effect, RerollEffect):
        rolled_by = effect.reroll.rolled_by
        owner = rolled_by.other if effect.enemy else rolled_by
        return {effect.reroll.value} if owner is side else set()
    if isinstance(effect, GrantEffect):
        granted = bearing.grants.get(effect.grants)
        if granted is None:
            return set()
        return set(routes(Bearing(granted, side, origin, bearing.grants)))
    if isinstance(effect, BlowEffect):
        return {stage.value for stage in effect.denies} if side is Side.ATTACKER else set()
    if isinstance(effect, AttackMarkEffect):
        return {MARKS} if side is Side.ATTACKER else set()
    if isinstance(effect, BarEffect):
        return {Stage.MAKE_ARMOUR_SAVES.value} if side is Side.TARGET else set()
    if isinstance(effect, WoundMultiplierEffect):
        weapon = side is Side.ATTACKER and origin is Namespace.WEAPON
        return {MULTIPLE_WOUNDS} if weapon else set()
    if isinstance(effect, VolleyEffect):
        weapon = side is Side.ATTACKER and origin is Namespace.WEAPON
        return {SHOTS} if weapon else set()
    return set()
