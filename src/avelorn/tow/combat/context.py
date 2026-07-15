"""The engagement context: the relational situation a combat is resolved in.

:class:`CombatContext` is the close-combat side, minimal today: who
charged, and the charge each made. Unknown facts stay unknown (None): a
conditional rule that needs an unknown answer stays unfactored and
reported, exactly like any other thing the math cannot honour — it is
never guessed. (Per-unit turn state — whether a unit moved, its charge —
lives on the :class:`~avelorn.tow.combat.contingent.Contingent`, not
here.)
"""

from dataclasses import dataclass

from avelorn.tow.combat.contingent import Charge


@dataclass(frozen=True)
class CombatContext:
    """What is known about the situation of a round of close combat.

    Holds who charged and how: each side's :class:`Charge`, or None for
    a side that did not charge this turn. The charge feeds the striking
    order today (:func:`~avelorn.tow.combat.melee.effective_initiative`)
    and the charging/arc conditions and combat-result bonuses (#28)
    later. ``first_round`` is whether this is the first round of the
    combat ("during the first round of any combat") — a charge's ensuing
    fight sets it True structurally. Grows a field per fact the rules
    need, like its shooting sibling.
    """

    a_charge: Charge | None = None
    b_charge: Charge | None = None
    first_round: bool | None = None  # "the first round of any combat"
