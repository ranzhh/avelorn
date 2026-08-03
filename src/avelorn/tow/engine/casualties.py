"""Remove Casualties: fold unsaved wounds into models removed.

The printed "Remove Casualties" step (the-shooting-phase and
the-combat-phase/remove-casualties-combat). Given the per-attack
unsaved-wound and instant-kill probabilities the dice walk produces,
this aggregates ``n`` identical attacks into the distribution of unsaved
wounds and the distribution of models removed. It is phase-agnostic:
shooting shots and close-combat attacks aggregate the same way once the
per-attack probabilities are known, so both phases share this step.
"""

import logging

from avelorn.core.dice import (
    binomial_distribution,
    cap_distribution,
    group_distribution,
    multinomial_outcomes,
)

logger = logging.getLogger(__name__)


def wound_and_casualties(
    n: int,
    *,
    p_unsaved: float,
    p_kill: float,
    wounds_per_model: int,
    targets: int | None,
) -> tuple[list[float], list[float]]:
    """Distribute a volley's unsaved wounds and the models it removes.

    ``p_unsaved`` is the per-attack chance of an unsaved wound of any
    class and ``p_kill`` the instant-kill subset of it. Unsaved wounds
    accumulate into whole slain models by ``wounds_per_model``; an
    instant kill removes a model outright. ``targets`` caps casualties at
    the unit's size when known; the wound distribution never depends on
    it.

    Returns:
        The distribution of unsaved wounds (index k = P(k unsaved
        wounds)) and the casualty distribution (index k = P(k models
        removed)).
    """
    if p_kill == 0:
        # Single outcome class: the multinomial degenerates to the binomial,
        # so keep the established path. Fold unsaved wounds into slain
        # models by Wounds-per-model, then cap at the unit's size; for
        # 1-Wound targets the fold is a no-op.
        distribution = binomial_distribution(n, p_unsaved)
        models = group_distribution(distribution, wounds_per_model)
        casualties = models if targets is None else cap_distribution(models, targets)
    else:
        distribution, casualties = _remove_casualties(
            n,
            p_wound_only=p_unsaved - p_kill,
            p_kill=p_kill,
            wounds_per_model=wounds_per_model,
            targets=targets,
        )
    logger.debug(
        "volley of %d: p_unsaved=%.3f p_kill=%.3f -> %d casualty buckets",
        n,
        p_unsaved,
        p_kill,
        len(casualties),
    )
    return distribution, casualties


def _remove_casualties(
    n: int,
    *,
    p_wound_only: float,
    p_kill: float,
    wounds_per_model: int,
    targets: int | None,
) -> tuple[list[float], list[float]]:
    # Class-aware aggregation, named after the printed "Remove Casualties"
    # step: enumerate (wounds, instant kills) counts over the volley by
    # multinomial. A kill removes a model outright; plain wounds accumulate
    # by Wounds-per-model. The unsaved-wound distribution counts both
    # classes (a Killing Blow is still an unsaved wound).
    # Seed with a zero of the callers' own numeric type: multiplying by 0 gives
    # 0.0 from a float and Fraction(0) from a Fraction, so an exact mass is
    # neither coerced on the first addition nor left as a bare int at an index no
    # outcome reaches (a volley too small to fill every casualty count).
    zero = (p_wound_only + p_kill) * 0
    distribution: list[float] = [zero] * (n + 1)
    size = n if targets is None else targets
    casualties: list[float] = [zero] * (size + 1)
    for (n_wound, n_kill), mass in multinomial_outcomes(n, (p_wound_only, p_kill)):
        distribution[n_wound + n_kill] += mass
        killed = min(n_kill + n_wound // wounds_per_model, size)
        casualties[killed] += mass
    return distribution, casualties
