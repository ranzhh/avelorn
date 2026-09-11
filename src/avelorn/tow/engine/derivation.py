"""How a reported roll target was arrived at.

A resolver reports a To Hit target of 5+. On its own that is an assertion: the
caller cannot tell a Ballistic Skill of 2 from a Ballistic Skill of 4 shooting
at long range from behind a hedge. This is the same number with its operands
still attached -- the chart value it started at, then every modifier that moved
it, each naming the printed rule that emitted it.

A step's ``modifier`` is in the rulebook's own sign convention, where a penalty
is negative: "-1 To Hit" reads as -1 here even though it *raises* the required
roll by one. ``target`` is where the roll stood after that step, so a reader
follows the arithmetic down the column rather than re-adding it.

A modifier the engine cannot attribute to a printed name carries ``source``
None. That happens where a bespoke code hook moved the target instead of a
compiled record, and saying so is the point: the alternative is a ledger whose
lines do not sum to the number above them.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from avelorn.tow.engine.attack import Modifier
from avelorn.tow.schema.stage import Stage


@dataclass(frozen=True)
class Step:
    """One modifier's contribution, and where it left the roll."""

    source: str | None
    modifier: int
    target: int


@dataclass(frozen=True)
class Derivation:
    """A roll target with its operands: what it started at, what moved it."""

    #: What the chart gave before any modifier, and the characteristic behind it.
    base: int
    basis: str
    steps: tuple[Step, ...]
    #: The target the walk used. Equals the last step's, or ``base`` with no steps.
    target: int


def hit_derivation(
    base: int,
    basis: str,
    reported: int,
    situational: int,
    modifiers: Sequence[Modifier],
) -> Derivation:
    """Gather the To Hit target's operands into a ledger.

    ``situational`` is the caller's own modifier -- cover, a large target, a
    fact the corpus cannot know -- which is folded into the chart lookup
    before the walk ever runs, so it leads. ``modifiers`` are the compiled
    records; only those landing on the To Hit roll unconditionally are shown,
    since one riding a natural face applies on that face alone and not to the
    printed target.

    ``reported`` is the target the volley actually used. Where the steps do
    not reach it, the remainder becomes a final unattributed step rather than
    a discrepancy between the ledger and the number it explains.

    Returns:
        The ledger, ending on ``reported``.
    """
    steps: list[Step] = []
    standing = base
    if situational:
        standing -= situational
        steps.append(Step(source="situational", modifier=situational, target=standing))
    for record in modifiers:
        if record.lands_on is not Stage.ROLL_TO_HIT or record.trigger is not None:
            continue
        standing += record.move
        steps.append(Step(source=record.source, modifier=-record.move, target=standing))
    if standing != reported:
        steps.append(Step(source=None, modifier=standing - reported, target=reported))
    return Derivation(base=base, basis=basis, steps=tuple(steps), target=reported)
