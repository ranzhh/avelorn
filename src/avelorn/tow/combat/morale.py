"""Morale tests: Leadership tests forced by the tide of battle.

Each is composed on another result's distribution — casualties, a combat
result — so a caller gets the outcome probabilities directly rather than
multiplying them by hand. The first is Make Panic Tests.

Make Panic Tests: the shooting sequence's final step, composed on
casualties. Sources (tow.whfb.app): the-shooting-phase/make-panic-tests,
the-shooting-phase/fall-back-or-flee,
the-shooting-phase/no-need-for-hysterics-shooting,
the-psychology-of-war/panic-tests. The printed model:

- A unit that loses more than a quarter (25%) of the models it
  contained at the start of the Shooting phase must immediately make a
  Panic test — a Leadership test. At most one Panic test is made per
  Shooting phase ("No Need for Hysterics").
- If the test is failed: a unit still containing more than half (50%)
  of the models it contained at the start of the battle Falls Back in
  Good Order; a unit reduced to half or fewer Flees.

This is the first seam composed on another result's distribution: each
casualty outcome branches through the trigger and the test, exactly.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import product

from avelorn.tow.combat.characteristic_tests import unit_pass_probability
from avelorn.tow.combat.melee import CombatResult
from avelorn.tow.combat.rules import resolve_rule
from avelorn.tow.combat.shooting import ShootingResult
from avelorn.tow.schema.psychology import PanicCause
from avelorn.tow.schema.rule import RerollEffect, Rule
from avelorn.tow.schema.stage import Stage
from avelorn.tow.schema.unit import Characteristic, Unit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PanicResult:
    """Exact outcome probabilities of the Make Panic Tests step."""

    p_test: float  # lost more than 25% of start-of-phase models (and survived)
    p_holds: float  # never tested, or tested and passed
    p_falls_back: float  # failed with more than half its battle strength left
    p_flees: float  # failed at half its battle strength or less
    p_destroyed: float  # every model lost: no unit remains to test
    reroll_from: str | None = None  # the rule that re-rolls a failed test, if any


def make_panic_tests(
    result: ShootingResult,
    defender: Unit,
    *,
    rules: Mapping[str, Rule] | None = None,
    battle_strength: int | None = None,
) -> PanicResult:
    """Resolve the panic step for one volley's casualty distribution.

    ``rules`` maps printed rule names to rule entries: a re-roll effect
    on this seam whose cause filter admits heavy casualties (this
    seam's only cause) re-rolls a failed test — once, whatever the
    source, per the printed re-roll rules. ``battle_strength`` is the
    unit's model count at the start of the battle, governing the
    printed Fall Back or Flee split; it defaults to the start-of-phase
    count — a unit yet to take any casualties.

    Returns:
        The exact probabilities of each panic outcome.

    Raises:
        ValueError: the result has no target unit size, the size is
            zero, or ``battle_strength`` is smaller than it.
    """
    size = result.target_models
    if size is None or size == 0:
        raise ValueError("panic needs the target unit's size (defenders)")
    battle = battle_strength if battle_strength is not None else size
    if battle < size:
        raise ValueError(f"battle strength ({battle}) cannot be below current size ({size})")

    p_pass = float(unit_pass_probability(defender, Characteristic.LEADERSHIP))
    reroll_from = _reroll_grant(defender, rules or {}, PanicCause.HEAVY_CASUALTIES)
    if reroll_from is not None:
        # A failed test is taken again: both dice, same natural bounds,
        # never more than once whatever the source.
        p_pass = p_pass + (1.0 - p_pass) * p_pass
    tested = holds = falls_back = flees = destroyed = 0.0
    for killed, mass in enumerate(result.casualties):
        if killed == size:
            destroyed += mass
        elif killed * 4 > size:  # "more than a quarter (25%)"
            tested += mass
            holds += mass * p_pass
            remaining = size - killed
            failed = mass * (1.0 - p_pass)
            if remaining * 2 > battle:  # "more than half (50%) ... still remain"
                falls_back += failed
            else:
                flees += failed
        else:
            holds += mass
    logger.debug(
        "panic: p_test=%.3f holds=%.3f falls back=%.3f flees=%.3f destroyed=%.3f",
        tested,
        holds,
        falls_back,
        flees,
        destroyed,
    )
    return PanicResult(
        p_test=tested,
        p_holds=holds,
        p_falls_back=falls_back,
        p_flees=flees,
        p_destroyed=destroyed,
        reroll_from=reroll_from,
    )


def _reroll_grant(defender: Unit, rules: Mapping[str, Rule], cause: PanicCause) -> str | None:
    # The first of the defender's rules granting a re-roll on this seam
    # for this cause; one grant is all a test can ever use.
    for printed in defender.special_rules:
        resolved = resolve_rule(printed, rules)
        if resolved is None:
            continue
        for effect in resolved.rule.effects:
            if (
                isinstance(effect, RerollEffect)
                and effect.stage is Stage.MAKE_PANIC_TESTS
                and (not effect.causes or cause in effect.causes)
            ):
                logger.debug("panic re-roll granted by %s", printed)
                return printed
    return None


@dataclass(frozen=True)
class SideBreak:
    """A side's Break-test outcomes for the rounds it loses.

    Only the losing side takes a Break test, so these are the printed
    outcomes for this side *conditioned on it being the loser*: the three
    sum to the probability this side lost the round. The winner takes no
    Break test — its follow-up / pursuit / reform choices are not modelled
    here.
    """

    p_gives_ground: float
    p_falls_back: float
    p_breaks: float


@dataclass(frozen=True)
class BreakResult:
    """Both sides' Break-test outcomes for one round of close combat.

    A round has at most one loser, so ``a`` and ``b`` are mutually
    exclusive — each is non-zero only across the outcomes where that side
    lost. ``p_draw`` is the chance of a drawn combat, in which neither side
    tests. The two sides' six outcome probabilities and ``p_draw`` sum to 1.
    """

    a: SideBreak
    b: SideBreak
    p_draw: float


def break_test(result: CombatResult, unit_a: Unit, unit_b: Unit) -> BreakResult:
    """Resolve the Break test for a scored combat round, for each side.

    Only the losing side rolls: 2D6, add the winner's margin, compare to
    its Leadership (highest value in the unit). A natural roll above
    Leadership Breaks and flees; a natural roll within it but a modified
    roll above Falls Back in Good Order; a modified roll within it — or a
    natural double 1 — Gives Ground (the-combat-phase/break-test). The
    winner takes no Break test (its follow-up and pursuit choices are not
    modelled here), and a drawn combat tests neither side.

    Composes on the signed margin distribution: ``unit_a`` is the
    positive-margin side, matching :func:`~avelorn.tow.combat.melee.fight`'s
    ``a``.

    Returns:
        Each side's Break-test outcomes for the rounds it loses, plus the
        drawn-combat probability.
    """
    a_leadership = unit_a.highest(Characteristic.LEADERSHIP) or 0
    b_leadership = unit_b.highest(Characteristic.LEADERSHIP) or 0
    logger.debug("break test: Ld %d (a) vs Ld %d (b)", a_leadership, b_leadership)
    return BreakResult(
        a=_side_break(
            result.margin, a_leadership, deficit=lambda lead: -lead if lead < 0 else None
        ),
        b=_side_break(
            result.margin, b_leadership, deficit=lambda lead: lead if lead > 0 else None
        ),
        p_draw=sum(mass for lead, mass in result.margin.items() if lead == 0),
    )


def _side_break(
    margin: Mapping[int, float], leadership: int, *, deficit: Callable[[int], int | None]
) -> SideBreak:
    # Aggregate one side's Break-test outcomes over the rounds it loses.
    # ``deficit(lead)`` is this side's losing margin at signed lead ``lead``,
    # or None when it did not lose (it won, or the combat was drawn) and so
    # takes no test.
    breaks = falls_back = gives_ground = 0.0
    for lead, mass in margin.items():
        loss = deficit(lead)
        if loss is None:
            continue
        p_break, p_fall, p_give = _break_outcomes(leadership, loss)
        breaks += mass * p_break
        falls_back += mass * p_fall
        gives_ground += mass * p_give
    return SideBreak(p_gives_ground=gives_ground, p_falls_back=falls_back, p_breaks=breaks)


def _break_outcomes(leadership: int, margin: int) -> tuple[float, float, float]:
    # The three Break-test outcome probabilities for a loser of ``leadership``
    # facing a winner's ``margin`` (>= 1), over an exact 2D6. A natural
    # double 1 always Gives Ground; otherwise a natural roll over Leadership
    # Breaks, a modified roll over it Falls Back, and the rest Gives Ground.
    breaks = falls_back = gives_ground = 0
    for first, second in product(range(1, 7), repeat=2):
        natural = first + second
        if natural == 2:  # natural double 1
            gives_ground += 1
        elif natural > leadership:
            breaks += 1
        elif natural + margin > leadership:
            falls_back += 1
        else:
            gives_ground += 1
    return breaks / 36, falls_back / 36, gives_ground / 36
