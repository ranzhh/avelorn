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
from collections.abc import Sequence
from typing import NamedTuple

from avelorn.core.dice import (
    binomial_distribution,
    cap_distribution,
    group_distribution,
    multinomial_outcomes,
)
from avelorn.core.distribution import Distribution, Probability

logger = logging.getLogger(__name__)


class AttackBatch(NamedTuple):
    """One homogeneous batch of attacks: its count and per-attack probabilities.

    The unit of composition for a heterogeneous strike (#46): a cavalry
    model's riders and mounts each throw a batch at their own line, and the
    round folds the batches' wounds together before removing casualties.
    """

    attacks: int
    p_unsaved: Probability
    p_kill: Probability


def wound_and_casualties(
    n: int,
    *,
    p_unsaved: Probability,
    p_kill: Probability,
    wounds_per_model: int,
    targets: int | None,
    damage: Distribution[int] | None = None,
) -> tuple[list[Probability], list[Probability]]:
    """Distribute a volley's unsaved wounds and the models it removes.

    ``p_unsaved`` is the per-attack chance of an unsaved wound of any
    class and ``p_kill`` the instant-kill subset of it. Unsaved wounds
    accumulate into whole slain models by ``wounds_per_model``; an
    instant kill removes a model outright. ``targets`` caps casualties at
    the unit's size when known; the wound distribution never depends on
    it.

    ``damage`` is the wounds each unsaved wound inflicts — Multiple
    Wounds (X)'s multiplier, a constant or a die rolled separately per
    wound (:func:`~avelorn.tow.engine.rules.effective_wound_multiplier`);
    None is the plain single wound. The printed cap is applied here:
    wounds a model cannot lose are discarded, never spilt onto the next
    (see :func:`_fell_by_count`). The unsaved-wound distribution still
    counts unsaved wounds, not the wounds they inflict.

    Returns:
        The distribution of unsaved wounds (index k = P(k unsaved
        wounds)) and the casualty distribution (index k = P(k models
        removed)).
    """
    if p_kill == 0 and damage is None:
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
            damage=damage,
        )
    logger.debug(
        "volley of %d: p_unsaved=%.3f p_kill=%.3f -> %d casualty buckets",
        n,
        p_unsaved,
        p_kill,
        len(casualties),
    )
    return distribution, casualties


def batched_wound_and_casualties(
    batches: Sequence[AttackBatch],
    *,
    wounds_per_model: int,
    targets: int | None,
    damage: Distribution[int] | None = None,
) -> tuple[list[Probability], list[Probability]]:
    """Distribute several independent batches' unsaved wounds and casualties.

    The heterogeneous counterpart of :func:`wound_and_casualties`: each batch
    resolves at its own per-attack probabilities, the batches' (wound, kill)
    joints convolve — independent counts add — and the fold to models and the
    size cap run once, on the combined distribution. Folding per batch would
    be wrong for multi-Wound targets: 2 wounds from one batch and 1 from
    another fell a whole 3-Wound model, where ``2//3 + 1//3`` fells none.

    ``damage`` reads as on :func:`wound_and_casualties`, and applies to the
    pooled wounds of *every* batch: the caller passes one only when all its
    batches' wounds are worth the same (a lone batch, or peers sharing the
    multiplier) — a pool mixing plain and multiplied wounds has no printed
    allocation order, so the caller leaves such a multiplier unfactored and
    reported instead of picking one silently.

    Returns:
        The distribution of unsaved wounds (index k = P(k unsaved wounds))
        and the casualty distribution (index k = P(k models removed)).
    """
    if len(batches) == 1:
        batch = batches[0]
        return wound_and_casualties(
            batch.attacks,
            p_unsaved=batch.p_unsaved,
            p_kill=batch.p_kill,
            wounds_per_model=wounds_per_model,
            targets=targets,
            damage=damage,
        )
    # Convolve the per-batch (plain wounds, instant kills) joints component-wise
    # — tuple outcomes, so an explicit component sum, never the concatenating
    # ``+`` (see avelorn.core.distribution's module docstring).
    joint: Distribution[tuple[int, int]] = Distribution.pure((0, 0))
    for batch in batches:
        outcomes = multinomial_outcomes(
            batch.attacks, (batch.p_unsaved - batch.p_kill, batch.p_kill)
        )
        one = Distribution({counts: mass for counts, mass in outcomes})
        joint = joint.combine(one, lambda a, b: (a[0] + b[0], a[1] + b[1]))
    total = sum(batch.attacks for batch in batches)
    size = total if targets is None else targets
    zero = sum((batch.p_unsaved for batch in batches), start=0) * 0
    distribution: list[Probability] = [zero] * (total + 1)
    casualties: list[Probability] = [zero] * (size + 1)
    fell = None if damage is None else _fell_by_count(total, damage, wounds_per_model)
    for (wounds, kills), mass in joint.mass.items():
        distribution[wounds + kills] += mass
        if fell is None:
            casualties[min(kills + wounds // wounds_per_model, size)] += mass
        else:
            for felled, share in fell[wounds].mass.items():
                casualties[min(kills + felled, size)] += mass * share
    return distribution, casualties


def _remove_casualties(
    n: int,
    *,
    p_wound_only: Probability,
    p_kill: Probability,
    wounds_per_model: int,
    targets: int | None,
    damage: Distribution[int] | None = None,
) -> tuple[list[Probability], list[Probability]]:
    # Class-aware aggregation, named after the printed "Remove Casualties"
    # step: enumerate (wounds, instant kills) counts over the volley by
    # multinomial. A kill removes a model outright; plain wounds accumulate
    # by Wounds-per-model — or, under a wound multiplier, through the
    # per-model absorb chain (_fell_by_count). The unsaved-wound distribution
    # counts both classes (a Killing Blow is still an unsaved wound).
    # Seed with a zero of the callers' own numeric type: multiplying by 0 gives
    # 0.0 from a float and Fraction(0) from a Fraction, so an exact mass is
    # neither coerced on the first addition nor left as a bare int at an index no
    # outcome reaches (a volley too small to fill every casualty count).
    zero = (p_wound_only + p_kill) * 0
    distribution: list[Probability] = [zero] * (n + 1)
    size = n if targets is None else targets
    casualties: list[Probability] = [zero] * (size + 1)
    fell = None if damage is None else _fell_by_count(n, damage, wounds_per_model)
    for (n_wound, n_kill), mass in multinomial_outcomes(n, (p_wound_only, p_kill)):
        distribution[n_wound + n_kill] += mass
        if fell is None:
            casualties[min(n_kill + n_wound // wounds_per_model, size)] += mass
        else:
            for felled, share in fell[n_wound].mass.items():
                casualties[min(n_kill + felled, size)] += mass * share
    return distribution, casualties


def _fell_by_count(
    n: int, damage: Distribution[int], wounds_per_model: int
) -> list[Distribution[int]]:
    # The distribution of models felled by exactly k multiplied wounds, for
    # every k up to ``n`` — the per-model absorb chain behind Multiple
    # Wounds (X). Wounds land on one model at a time: each rolls its damage
    # separately (the printed per-wound dice roll) and the model under fire
    # absorbs it up to its remaining Wounds; a wound that reaches zero fells
    # it and the next wound meets a fresh model. Both printed cap clauses —
    # "excess wounds ... have no additional effect", "do not 'spill over'" —
    # are this discard: damage past the model's remaining Wounds goes nowhere.
    states: Distribution[tuple[int, int]] = Distribution.pure((0, wounds_per_model))
    by_count = [states.map(lambda state: state[0])]
    for _ in range(n):
        states = states >> (
            lambda state: damage.map(lambda dealt: _struck(state, dealt, wounds_per_model))
        )
        by_count.append(states.map(lambda state: state[0]))
    return by_count


def _struck(state: tuple[int, int], dealt: int, wounds_per_model: int) -> tuple[int, int]:
    # One multiplied wound landing on the model under fire: felled and
    # replaced by a fresh one, or standing with fewer Wounds.
    felled, remaining = state
    if dealt >= remaining:
        return felled + 1, wounds_per_model
    return felled, remaining - dealt
