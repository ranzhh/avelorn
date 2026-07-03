"""Make Panic Tests: the shooting sequence's final step, composed on casualties.

Sources (tow.whfb.app): the-shooting-phase/make-panic-tests,
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
from collections.abc import Mapping
from dataclasses import dataclass

from avelorn.tow.combat.characteristic_tests import unit_pass_probability
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
