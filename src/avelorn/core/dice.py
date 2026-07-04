"""Probability primitives for D6-based dice mechanics.

Pure math only: no game rules live here. Game packages turn their charts
into roll targets, then use these helpers to turn targets into
probabilities and distributions.
"""

import logging
import random
from collections.abc import Iterator, Sequence
from math import comb

logger = logging.getLogger(__name__)


def p_d6_at_least(target: int) -> float:
    """Probability that a single D6 rolls ``target`` or higher.

    Targets of 1 or lower are certain; targets above 6 are impossible.
    Game rules such as "a natural 1 always fails" belong to callers, who
    should adjust the target before calling.

    Returns:
        The success probability, in [0.0, 1.0].
    """
    if target <= 1:
        return 1.0
    if target > 6:
        return 0.0
    return (7 - target) / 6


def binomial_pmf(successes: int, trials: int, p: float) -> float:
    """Probability of exactly ``successes`` hits in ``trials`` independent attempts.

    Returns:
        P(X = successes) for X ~ Binomial(trials, p).
    """
    misses = trials - successes
    return comb(trials, successes) * p**successes * (1.0 - p) ** misses


def binomial_distribution(trials: int, p: float) -> list[float]:
    """Full probability mass function for a binomial outcome.

    Returns:
        A list of length ``trials + 1`` where index ``k`` is P(k successes).
    """
    logger.debug("binomial distribution over %d trials, p=%.3f", trials, p)
    return [binomial_pmf(k, trials, p) for k in range(trials + 1)]


def multinomial_outcomes(
    trials: int, probabilities: Sequence[float]
) -> Iterator[tuple[tuple[int, ...], float]]:
    """Enumerate class-count vectors of a multinomial with their probabilities.

    ``probabilities`` are the per-trial probabilities of each class; any
    remaining mass is an implicit "nothing" class whose count is not
    reported. With one class this reduces to the binomial.

    Yields:
        ``(counts, probability)`` per distinct count vector, where
        ``counts[i]`` is how many of the ``trials`` fell in class ``i``.
        The probabilities of all vectors sum to 1.

    Raises:
        ValueError: ``trials`` is negative.
    """
    if trials < 0:
        raise ValueError("trials must be >= 0")
    p_rest = 1.0 - sum(probabilities)

    def _vectors(
        remaining: int, index: int, counts: tuple[int, ...], mass: float
    ) -> Iterator[tuple[tuple[int, ...], float]]:
        if index == len(probabilities):
            yield counts, mass * p_rest**remaining
            return
        p = probabilities[index]
        for k in range(remaining + 1):
            yield from _vectors(
                remaining - k, index + 1, (*counts, k), mass * comb(remaining, k) * p**k
            )

    yield from _vectors(trials, 0, (), 1.0)


def cap_distribution(distribution: list[float], cap: int) -> list[float]:
    """Fold all probability mass at or above ``cap`` onto index ``cap``.

    Models a ceiling on a count: a volley cannot remove more models than a
    unit contains, so every outcome of ``cap`` or more collapses to exactly
    ``cap``. Pure redistribution — the returned masses still sum to 1.

    Returns:
        A list of length ``min(len(distribution), cap + 1)``.

    Raises:
        ValueError: ``cap`` is negative.
    """
    if cap < 0:
        raise ValueError("cap must be >= 0")
    if cap >= len(distribution) - 1:
        return list(distribution)
    logger.debug("capping distribution at %d (length %d)", cap, len(distribution))
    return [*distribution[:cap], sum(distribution[cap:])]


def group_distribution(distribution: list[float], group_size: int) -> list[float]:
    """Collapse each ``group_size`` consecutive outcomes into one bucket.

    Outcome ``k`` maps to bucket ``k // group_size`` — the number of whole
    groups it completes. This models, for example, unsaved wounds
    accumulating into whole slain multi-Wound models (three wounds per
    Ogre), where the leftover wounds sit on a survivor. Pure
    redistribution — the returned masses still sum to 1.

    Returns:
        A list of length ``(len(distribution) - 1) // group_size + 1``.

    Raises:
        ValueError: ``group_size`` is less than 1.
    """
    if group_size < 1:
        raise ValueError("group_size must be >= 1")
    if group_size == 1:
        return list(distribution)
    buckets = [0.0] * ((len(distribution) - 1) // group_size + 1)
    for outcome, mass in enumerate(distribution):
        buckets[outcome // group_size] += mass
    logger.debug("grouping distribution by %d into %d buckets", group_size, len(buckets))
    return buckets


def sample(distribution: list[float], rng: random.Random | None = None) -> int:
    """Draw one concrete outcome from a distribution (index k = P(outcome k)).

    Sampling the computed distribution is statistically identical to
    rolling the dice, which makes this the building block for "roll it
    for me" actions. Pass a seeded ``rng`` for reproducible draws.

    Returns:
        The sampled outcome index, in 0..len(distribution) - 1.
    """
    generator = rng if rng is not None else random.Random()
    outcome = generator.choices(range(len(distribution)), weights=distribution, k=1)[0]
    logger.debug("sampled %d from a %d-outcome distribution", outcome, len(distribution))
    return outcome


def expected_value(distribution: Sequence[float]) -> float:
    """Expected outcome of a distribution over the indices 0..n.

    Returns:
        The index-weighted mean (e.g. the mean number of successes or
        casualties, whichever the distribution counts).
    """
    return sum(k * p for k, p in enumerate(distribution))
