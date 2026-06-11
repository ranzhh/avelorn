"""Probability primitives for D6-based dice mechanics.

Pure math only: no game rules live here. Game packages turn their charts
into roll targets, then use these helpers to turn targets into
probabilities and distributions.
"""

from math import comb


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
    return [binomial_pmf(k, trials, p) for k in range(trials + 1)]


def expected_value(distribution: list[float]) -> float:
    """Expected outcome of a distribution produced by :func:`binomial_distribution`.

    Returns:
        The mean number of successes.
    """
    return sum(k * p for k, p in enumerate(distribution))
