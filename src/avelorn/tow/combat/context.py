"""The engagement contexts: the situation an action is resolved in.

One per phase. :class:`EngagementContext` is the shooting side — its
printed home is the sequence's first sub-phase, "Choose Unit & Declare
Target", where range and line of sight are checked.
:class:`CombatContext` is the close-combat side, minimal today: who
charged, and the charge each made. Unknown facts stay unknown (None): a
conditional rule that needs an unknown answer stays unfactored and
reported, exactly like any other thing the math cannot honour — it is
never guessed.
"""

from dataclasses import dataclass

from avelorn.tow.combat.contingent import Charge


@dataclass(frozen=True)
class EngagementContext:
    """What is known about the situation of the shooting unit."""

    moved: bool | None = None  # "moved for any reason during this turn"
    distance: int | None = None  # inches to the target


@dataclass(frozen=True)
class CombatContext:
    """What is known about the situation of a round of close combat.

    Holds who charged and how: each side's :class:`Charge`, or None for
    a side that did not charge this turn. The charge feeds the striking
    order today (:func:`~avelorn.tow.combat.melee.effective_initiative`)
    and the charging/arc conditions and combat-result bonuses (#28)
    later. Grows a field per fact the rules need, like its shooting
    sibling.
    """

    a_charge: Charge | None = None
    b_charge: Charge | None = None
