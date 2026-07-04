"""A querying layer over the engine's probability distributions.

The combat math produces *distributions* (a volley's wounds, the
casualties it inflicts, the models a unit has left). Warhammer is decided
on those distributions, not on their averages: "what is the chance at
most three survive" is a different — and more useful — question than
"how many die on average".

This layer answers such questions *exactly*. It is deliberately split:

- :class:`Distribution` and :func:`evaluate` are engine-agnostic. They
  know nothing about shooting, units, or rules — only how to reduce a
  probability mass function to an exact number. A future combat phase, or
  a composed result (casualties feeding a panic test), exposes the same
  type and is queried the same way.
- :func:`result_distributions` and :func:`fight_distributions` are the
  combat-coupled pieces: each names the variables its result — a
  :class:`ShootingResult`, a :class:`FightResult` — carries.

The intended division of labour: a caller (an agent, the CLI, a future
MCP tool) translates a natural-language question into a structured
:class:`Predicate` over a named variable; this layer returns the exact
probability. The arithmetic never leaves deterministic code.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum

from avelorn.core.dice import expected_value
from avelorn.tow.combat.melee import FightResult
from avelorn.tow.combat.shooting import ShootingResult

logger = logging.getLogger(__name__)


class Comparator(StrEnum):
    """The closed set of predicates this layer can answer exactly."""

    AT_MOST = "at_most"  # P(value <= k)
    AT_LEAST = "at_least"  # P(value >= k)
    EXACTLY = "exactly"  # P(value == k)
    BETWEEN = "between"  # P(low <= value <= high), inclusive


@dataclass(frozen=True)
class Predicate:
    """A structured question about a distribution: an operator and operands.

    ``value`` is the threshold (the lower bound for ``BETWEEN``); ``upper``
    is the inclusive upper bound and is required for — and only for —
    ``BETWEEN``. The shape is intentionally JSON-schema friendly: an
    agent fills typed fields rather than composing a string.
    """

    op: Comparator
    value: int
    upper: int | None = None

    def __post_init__(self) -> None:
        """Reject ill-formed predicates at construction.

        Raises:
            ValueError: the threshold is negative, BETWEEN lacks an upper
                bound or has an inverted one, or upper is set for a
                non-interval operator.
        """
        if self.value < 0:
            raise ValueError("value must be >= 0")
        if self.op is Comparator.BETWEEN:
            if self.upper is None:
                raise ValueError("BETWEEN requires an upper bound")
            if self.upper < self.value:
                raise ValueError(f"upper ({self.upper}) must be >= value ({self.value})")
        elif self.upper is not None:
            raise ValueError(f"upper is only valid for BETWEEN, not {self.op}")


@dataclass(frozen=True)
class Distribution:
    """A named probability mass function with exact query operators.

    ``pmf[k]`` is P(value == k); the value's support is ``0 .. len(pmf)-1``.
    Outcomes outside the support have probability zero, so queries past the
    support are well defined (an ``at_least`` past the top is 0.0, an
    ``at_most`` past the top is 1.0).
    """

    name: str
    pmf: tuple[float, ...]

    def exactly(self, k: int) -> float:
        """P(value == k).

        Returns:
            The mass at ``k``, or 0.0 if ``k`` is outside the support.
        """
        return self.pmf[k] if 0 <= k < len(self.pmf) else 0.0

    def at_most(self, k: int) -> float:
        """P(value <= k).

        Returns:
            The cumulative mass up to and including ``k``.
        """
        if k < 0:
            return 0.0
        return sum(self.pmf[: k + 1])

    def at_least(self, k: int) -> float:
        """P(value >= k).

        Returns:
            The tail mass at or above ``k``.
        """
        if k <= 0:
            return sum(self.pmf)
        return sum(self.pmf[k:])

    def between(self, low: int, high: int) -> float:
        """P(low <= value <= high), inclusive on both ends.

        Returns:
            The mass in the inclusive interval.
        """
        return sum(self.pmf[max(low, 0) : high + 1]) if high >= 0 else 0.0

    def mean(self) -> float:
        """The expectation of the distribution.

        Returns:
            Sum of ``k * P(value == k)``.
        """
        return expected_value(self.pmf)

    def mode(self) -> int:
        """The single most likely outcome.

        Returns:
            The index of maximum mass (the lowest such index on a tie).

        Raises:
            ValueError: the distribution has no outcomes (empty pmf).
        """
        if not self.pmf:
            raise ValueError("mode is undefined for an empty distribution")
        return max(range(len(self.pmf)), key=self.pmf.__getitem__)


def evaluate(distribution: Distribution, predicate: Predicate) -> float:
    """Answer a structured predicate against a distribution, exactly.

    This is the single query primitive the agent-facing surface routes
    through: a closed operator set, so a caller can never pose a question
    the engine cannot answer exactly.

    Returns:
        The probability the predicate holds, in [0.0, 1.0].
    """
    match predicate.op:
        case Comparator.AT_MOST:
            probability = distribution.at_most(predicate.value)
        case Comparator.AT_LEAST:
            probability = distribution.at_least(predicate.value)
        case Comparator.EXACTLY:
            probability = distribution.exactly(predicate.value)
        case Comparator.BETWEEN:
            assert predicate.upper is not None  # guaranteed by Predicate
            probability = distribution.between(predicate.value, predicate.upper)
    logger.debug(
        "P(%s %s %s) = %.4f",
        distribution.name,
        predicate.op,
        predicate.value if predicate.upper is None else f"{predicate.value}..{predicate.upper}",
        probability,
    )
    return probability


def result_distributions(result: ShootingResult) -> dict[str, Distribution]:
    """Expose a shooting result's outcomes as named, queryable distributions.

    Always provides ``wounds`` (unsaved wounds inflicted) and ``casualties``
    (models removed). ``survivors`` is provided only when the target unit's
    size is known (``result.target_models``); without a size, "how many
    survive" has no defined answer and the variable is simply absent rather
    than guessed.

    Returns:
        A mapping of variable name to :class:`Distribution`.
    """
    distributions = {
        "wounds": Distribution("wounds", tuple(result.distribution)),
        "casualties": Distribution("casualties", tuple(result.casualties)),
    }
    size = result.target_models
    if size is not None:
        distributions["survivors"] = _mirror_survivors("survivors", result.casualties, size)
    return distributions


def _mirror_survivors(name: str, casualties: list[float], size: int) -> Distribution:
    """Mirror a casualty distribution into a survivors distribution over 0..size.

    survivors = size - casualties: P(survivors == s) == P(casualties ==
    size - s). ``casualties`` may be shorter than ``size + 1`` (a volley too
    small to reach the unit's size never bites the cap), so the full 0..size
    support is built and each casualty mass placed at its mirror index,
    leaving unreachable survivor counts at zero.

    Returns:
        The survivors distribution.
    """
    survivors = [0.0] * (size + 1)
    for removed, mass in enumerate(casualties):
        survivors[size - removed] = mass
    logger.debug("survivors distribution mirrored over size %d", size)
    return Distribution(name, tuple(survivors))


def query_result(result: ShootingResult, variable: str, predicate: Predicate) -> float:
    """Evaluate a predicate against one named variable of a shooting result.

    The convenience entry point a caller uses end to end: pick a variable
    by name, pose a structured predicate, get an exact probability.

    Returns:
        The probability the predicate holds, in [0.0, 1.0].

    Raises:
        KeyError: the variable is not available for this result (e.g.
            ``survivors`` when the target size is unknown). The message
            lists the variables that are available.
    """
    distributions = result_distributions(result)
    distribution = distributions.get(variable)
    if distribution is None:
        available = ", ".join(sorted(distributions))
        raise KeyError(f"no variable {variable!r} for this result (available: {available})")
    return evaluate(distribution, predicate)


def fight_distributions(result: FightResult) -> dict[str, Distribution]:
    """Expose a close-combat round's outcomes as named, queryable distributions.

    The second producer of queryable distributions: a :class:`FightResult`
    exposes, per side, its models-removed (``a_casualties``/``b_casualties``)
    and models-surviving (``a_survivors``/``b_survivors``) counts — queried
    with the same :func:`evaluate` and :class:`Predicate` as shooting. Each
    side's size is the length of its casualty marginal.

    Returns:
        A mapping of variable name to :class:`Distribution`.
    """
    distributions: dict[str, Distribution] = {}
    for side, casualties in (("a", result.a_casualties), ("b", result.b_casualties)):
        size = len(casualties) - 1
        distributions[f"{side}_casualties"] = Distribution(f"{side}_casualties", tuple(casualties))
        distributions[f"{side}_survivors"] = _mirror_survivors(
            f"{side}_survivors", casualties, size
        )
    return distributions
