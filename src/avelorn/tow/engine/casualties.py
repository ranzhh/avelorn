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

from avelorn.core.dice import binomial_distribution, multinomial_outcomes
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


class Toll(NamedTuple):
    """What a strike cost its target, as the printed steps count it.

    ``wounds`` is unsaved wounds, the figure the walk produces (a Killing
    Blow is one of them, as the page counts it). ``felled`` is models
    removed. ``inflicted`` is the Wounds the target actually lost — the
    combat-result figure: excess a model cannot lose is already discarded,
    a model slain outright counts its whole allotment, and the total is
    capped at the Wounds the unit has to give. For 1-Wound targets all
    three coincide, which is why the corpus has never had to tell them
    apart.
    """

    wounds: int
    felled: int
    inflicted: int


def _reach(
    batches: Sequence[AttackBatch],
    wounds_per_model: int,
    damage: Distribution[int] | None,
    targets: int | None,
) -> int:
    # The most models a strike could remove: what the attacks can reach, and
    # what the unit has to lose. One wound takes a whole model when it can kill
    # outright or carries a multiplier worth the model's Wounds; otherwise it
    # takes Wounds-per-model of them to fell one. This bounds the casualty
    # distribution, so a fold reports no bucket its attacks could never fill.
    total = sum(batch.attacks for batch in batches)
    by_attacks = (
        total
        if damage is not None or any(batch.p_kill for batch in batches)
        else total // wounds_per_model
    )
    return by_attacks if targets is None else min(by_attacks, targets)


def strike_toll(
    batches: Sequence[AttackBatch],
    *,
    wounds_per_model: int,
    targets: int | None,
    damage: Distribution[int] | None = None,
) -> Distribution[Toll]:
    """The joint distribution of what a pooled strike cost its target.

    The one enumeration behind every figure this module reports: the
    batches' (plain wound, instant kill) counts convolve — independent
    counts add — and each branch resolves to a whole :class:`Toll`. The
    three components must travel together because they are correlated:
    a round removes models by ``felled`` and scores by ``inflicted``, and
    differencing marginals would lose the link between them.

    ``damage`` reads as on :func:`wound_and_casualties`.

    Returns:
        The distribution over tolls.
    """
    total = sum(batch.attacks for batch in batches)
    size = _reach(batches, wounds_per_model, damage, targets)
    # The Wounds the unit has to give — its models' whole allotment, so a
    # strike scores no more than the target could actually lose. Unknown
    # without a unit size, and then uncapped, as the wound distribution is.
    allotment = None if targets is None else targets * wounds_per_model
    if len(batches) == 1 and batches[0].p_kill == 0 and damage is None:
        # Single outcome class: the multinomial degenerates to the binomial,
        # so keep the established path. Every plain wound is absorbed whole —
        # a one-Wound hit is never excess — so inflicted counts them all.
        batch = batches[0]
        return Distribution(
            {
                Toll(k, min(k // wounds_per_model, size), _capped(k, allotment)): mass
                for k, mass in enumerate(binomial_distribution(batch.attacks, batch.p_unsaved))
            }
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
    absorbed = None if damage is None else _absorb(total, damage, wounds_per_model)
    tolls: dict[Toll, Probability] = {}
    for (wounds, kills), mass in joint.mass.items():
        # A model slain outright lost its whole allotment, so an instant kill
        # scores that much; a plain wound scores the one Wound it takes.
        for felled, taken, share in (
            [(wounds // wounds_per_model, wounds, 1)]
            if absorbed is None
            else [(f, t, p) for (f, t), p in absorbed[wounds].mass.items()]
        ):
            entry = Toll(
                wounds + kills,
                min(kills + felled, size),
                _capped(taken + kills * wounds_per_model, allotment),
            )
            tolls[entry] = tolls.get(entry, 0) + mass * share
    return Distribution(tolls)


def _capped(inflicted: int, allotment: int | None) -> int:
    # Wounds inflicted, held to what the unit had to lose.
    return inflicted if allotment is None else min(inflicted, allotment)


def _marginals(
    toll: Distribution[Toll], total: int, size: int
) -> tuple[list[Probability], list[Probability]]:
    # A toll distribution as the two lists this module has always returned.
    # The lists keep their full length whatever the toll reached, so an index
    # no outcome touches still reads as a zero of the callers' numeric type.
    zero = sum(toll.mass.values(), start=0) * 0
    distribution: list[Probability] = [zero] * (total + 1)
    casualties: list[Probability] = [zero] * (size + 1)
    for entry, mass in toll.mass.items():
        distribution[entry.wounds] += mass
        casualties[entry.felled] += mass
    return distribution, casualties


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
    (see :func:`_absorb`). The unsaved-wound distribution still
    counts unsaved wounds, not the wounds they inflict.

    Returns:
        The distribution of unsaved wounds (index k = P(k unsaved
        wounds)) and the casualty distribution (index k = P(k models
        removed)).
    """
    batch = [AttackBatch(n, p_unsaved, p_kill)]
    distribution, casualties = _marginals(
        strike_toll(
            batch,
            wounds_per_model=wounds_per_model,
            targets=targets,
            damage=damage,
        ),
        n,
        _reach(batch, wounds_per_model, damage, targets),
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
    total = sum(batch.attacks for batch in batches)
    return _marginals(
        strike_toll(batches, wounds_per_model=wounds_per_model, targets=targets, damage=damage),
        total,
        _reach(batches, wounds_per_model, damage, targets),
    )


def _absorb(
    n: int, damage: Distribution[int], wounds_per_model: int
) -> list[Distribution[tuple[int, int]]]:
    # The joint of (models felled, Wounds absorbed) by exactly k multiplied
    # wounds, for every k up to ``n`` — the per-model absorb chain behind
    # Multiple Wounds (X). Wounds land on one model at a time: each rolls its
    # damage separately (the printed per-wound dice roll) and the model under
    # fire absorbs it up to its remaining Wounds; a wound that reaches zero
    # fells it and the next wound meets a fresh model. Both printed cap
    # clauses — "excess wounds ... have no additional effect", "do not 'spill
    # over'" — are that discard: damage past the model's remaining Wounds goes
    # nowhere, so it is felled *and* absorbed that the chain reports, never the
    # damage rolled. What a felled model absorbed is its whole allotment, so
    # the absorbed total follows from the state: the models already down, plus
    # what the one under fire has taken.
    absorbed = lambda state: state[0] * wounds_per_model + (wounds_per_model - state[1])  # noqa: E731
    states: Distribution[tuple[int, int]] = Distribution.pure((0, wounds_per_model))
    by_count = [states.map(lambda state: (state[0], absorbed(state)))]
    for _ in range(n):
        states = states >> (
            lambda state: damage.map(lambda dealt: _struck(state, dealt, wounds_per_model))
        )
        by_count.append(states.map(lambda state: (state[0], absorbed(state))))
    return by_count


def _struck(state: tuple[int, int], dealt: int, wounds_per_model: int) -> tuple[int, int]:
    # One multiplied wound landing on the model under fire: felled and
    # replaced by a fresh one, or standing with fewer Wounds.
    felled, remaining = state
    if dealt >= remaining:
        return felled + 1, wounds_per_model
    return felled, remaining - dealt
