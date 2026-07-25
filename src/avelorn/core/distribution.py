"""A probability distribution as a first-class, composable value.

Pure math, no game rules (like the rest of ``core``). A ``Distribution[T]``
maps each outcome to its probability and gives the engine one shared way to
*compose* stochastic steps:

- relabel outcomes with :meth:`map` (a deterministic ``T -> U``);
- chain a stochastic step — a function ``T -> Distribution[U]`` — with
  :meth:`bind`, which resolves the step at every outcome and mixes the results
  by probability. ``bind`` is the fold ("weight each branch, sum") written
  once, here, so no caller spells it out again.

Formally this is the discrete probability monad: :meth:`pure` is a point mass,
:meth:`bind` is the mix, and the two obey the monad laws (checked in the tests).
Everything the engine passes around as a bare ``list[float]`` count-pmf is
:meth:`from_counts` of this type; the named count-pmf in
:mod:`avelorn.tow.query` is a special case (integer outcomes plus predicate
queries) that this subsumes.
"""

from collections import defaultdict
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass

# Alternatives, if we ever outgrow this hand-roll — noted so we remember them:
#   - icepool (https://github.com/HighDiceRoller/icepool): exact dice-pool
#     probabilities with a fast dynamic-programming algorithm. The right tool if
#     bind's full-joint materialisation ever blows up on wide or deeply chained
#     steps (a whole-battle fold), which the naive mix below does not guard.
#   - lea (https://pypi.org/project/lea/): general discrete distributions with
#     conditioning and Bayesian inference built in.
# We keep our own because it is tiny, dependency-free, and drops straight onto
# the existing list[float] / Fraction pmfs. Neither library solves the part that
# actually matters — engine steps typed as T -> Distribution[T] arrows — so that
# design is ours to build regardless of which Distribution we stand on.


@dataclass(frozen=True)
class Distribution[T: Hashable]:
    """An exact discrete distribution: each outcome mapped to its probability.

    Outcomes are any hashable value — an integer count, an enum member, a whole
    game state — so the same type carries a volley's casualties, a combat's
    winner, or a unit's surviving strength. Outcomes absent from ``mass`` have
    probability zero. A well-formed distribution's masses sum to 1.0
    (:meth:`total`); :meth:`bind` and :meth:`map` preserve that.
    """

    mass: Mapping[T, float]

    @classmethod
    def pure(cls, outcome: T) -> "Distribution[T]":
        """The point mass on ``outcome`` — the monad's ``return``.

        Returns:
            A distribution certain to yield ``outcome``.
        """
        return cls({outcome: 1.0})

    @staticmethod
    def from_counts(pmf: Sequence[float]) -> "Distribution[int]":
        """Lift a count-pmf (index ``k`` = P(value == ``k``)) into a distribution.

        The adapter for the engine's existing ``list[float]`` distributions —
        a volley's casualties, a round's losses. Zero-mass counts are dropped.

        Returns:
            A distribution over the integer counts ``0 .. len(pmf) - 1``.
        """
        return Distribution({count: p for count, p in enumerate(pmf) if p != 0.0})

    def map[U: Hashable](self, relabel: Callable[[T], U]) -> "Distribution[U]":
        """Relabel every outcome by ``relabel``, merging any that collide.

        A deterministic change of variable — survivors from casualties, a winner
        from a signed margin. Colliding images sum their mass.

        Returns:
            The distribution over the relabelled outcomes.
        """
        folded: dict[U, float] = defaultdict(float)
        for outcome, p in self.mass.items():
            folded[relabel(outcome)] += p
        return Distribution(dict(folded))

    def bind[U: Hashable](self, step: Callable[[T], "Distribution[U]"]) -> "Distribution[U]":
        """Chain a stochastic ``step`` onto this distribution and mix — the fold.

        ``step`` maps each outcome to its own distribution (the downstream
        resolved *given* that outcome). The result weights every branch by the
        outcome's probability and sums: ``Σ_x P(x) · step(x)``. This is the one
        place the mix lives; callers compose instead of hand-writing it.

        Returns:
            The mixed distribution over the downstream outcomes.
        """
        folded: dict[U, float] = defaultdict(float)
        for outcome, p in self.mass.items():
            for downstream, q in step(outcome).mass.items():
                folded[downstream] += p * q
        return Distribution(dict(folded))

    def prob(self, predicate: Callable[[T], bool]) -> float:
        """The probability that ``predicate`` holds of the outcome.

        Subsumes the count queries (``at least``, ``exactly``, …) — each is a
        predicate: ``prob(lambda k: k >= 1)``, ``prob(lambda k: k == 0)``.

        Returns:
            The summed mass of outcomes satisfying ``predicate``, in [0, 1].
        """
        return sum(p for outcome, p in self.mass.items() if predicate(outcome))

    def expect(self, value: Callable[[T], float]) -> float:
        """The expectation of ``value`` over the distribution: ``E[value(X)]``.

        With the identity for a count distribution this is the mean number of
        casualties; with any other function it is the expectation of that
        function of the outcome.

        Returns:
            ``Σ_x P(x) · value(x)``.
        """
        return sum(value(outcome) * p for outcome, p in self.mass.items())

    def total(self) -> float:
        """The total mass — 1.0 for a well-formed distribution.

        Returns:
            The sum of all outcome probabilities.
        """
        return sum(self.mass.values())
