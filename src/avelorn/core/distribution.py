"""A probability distribution as a first-class, composable value.

Pure math, no game rules (like the rest of ``core``). A ``Distribution[T]``
maps each outcome to its probability and gives the engine one shared way to
*compose* stochastic steps:

- relabel outcomes with :meth:`map` (a deterministic ``T -> U``);
- chain a stochastic step — a function ``T -> Distribution[U]`` — with
  :meth:`bind`, which resolves the step at every outcome and mixes the results
  by probability. ``bind`` is the fold ("weight each branch, sum") written
  once, here, so no caller spells it out again.

``dist >> step`` is :meth:`bind` spelled as an operator, and a :class:`Step`
wraps such a step as a value so a whole sequence composes before any
distribution reaches it (``to_hit >> to_wound >> saves``). Arithmetic on
outcomes — :meth:`__add__` and the rest — goes through :meth:`combine`.

The arithmetic operators mean whatever the *outcome type's* operator means, so
they serve numeric outcomes and nothing else. A distribution over vectors of
per-class counts (``(wounds, kills)``, the shape the multinomial aggregation in
:mod:`avelorn.tow.engine.casualties` produces) does not add component-wise:
``+`` concatenates the tuples instead, silently. Vector outcomes need
:meth:`combine` with a component-wise operation, or a distribution per class.
Naming that gap here rather than guessing at an operator for it.

Formally this is the discrete probability monad: :meth:`pure` is a point mass,
:meth:`bind` is the mix, and the two obey the monad laws (checked in the tests).
Everything the engine passes around as a bare ``list[float]`` count-pmf is
:meth:`from_counts` of this type; the named count-pmf in
:mod:`avelorn.tow.query` is a special case (integer outcomes plus predicate
queries) that this subsumes.
"""

import operator
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

    def __rshift__[U: Hashable](self, step: Callable[[T], "Distribution[U]"]) -> "Distribution[U]":
        """``dist >> step`` is :meth:`bind` — feed this distribution into ``step``.

        Reads left to right in the order the engine resolves: a distribution,
        then the step it flows into. ``step`` is any callable of that shape, so
        a plain function and a :class:`Step` both chain.

        Returns:
            The mixed distribution over the downstream outcomes.
        """
        return self.bind(step)

    def combine[U: Hashable, V: Hashable](
        self, other: "Distribution[U]", op: Callable[[T, U], V]
    ) -> "Distribution[V]":
        """Apply ``op`` to **independent** draws from this distribution and ``other``.

        The lift every arithmetic operator below is written in terms of: it takes
        the joint of two unrelated variables and relabels each pair by ``op``.
        Being built on :meth:`bind` and :meth:`map`, it adds no second fold.

        Independence is an assumption about the two arguments that this cannot
        check. Where two quantities are correlated — two sides of one combat,
        where the same volley thins one and scores for the other — the joint has
        to be built where the correlation is known, not recovered from marginals
        here.

        Returns:
            The distribution of ``op(x, y)`` over independent ``x``, ``y``.
        """
        return self.bind(lambda outcome: other.map(lambda downstream: op(outcome, downstream)))

    @classmethod
    def _lifted(cls, value: "Distribution[T] | T") -> "Distribution[T]":
        # An arithmetic operand either way: a distribution stands, a bare
        # outcome becomes the certainty of itself.
        return value if isinstance(value, Distribution) else cls.pure(value)

    def __add__(self, other: "Distribution[T] | T") -> "Distribution[T]":
        """``a + b`` — the sum of independent draws, or a constant shift.

        With a distribution on the right this is the convolution: the total of
        two unrelated quantities, a second volley's casualties on top of the
        first. With a bare outcome it shifts every value by that constant, which
        is how a fixed edge (a Rank Bonus) enters a distribution of leads.

        The sum is whatever ``+`` means for the outcome type, which is a total
        only for numbers. On a tuple outcome — a vector of per-class counts, as
        the multinomial aggregation produces — ``+`` concatenates and the result
        is longer tuples, not component sums. Nothing raises. Adding such
        outcomes component-wise needs :meth:`combine` with an explicit
        operation; see the module docstring.

        Returns:
            The distribution of the sum.
        """
        return self.combine(self._lifted(other), operator.add)

    def __radd__(self, other: T) -> "Distribution[T]":
        """``value + dist`` — the sum with a constant on the left.

        Python only reaches a reflected operator when the left operand is of
        another type, so ``other`` is always a bare outcome here, never a
        distribution. The constant stays on the left so a non-commutative ``+``
        still means what it reads as.

        Returns:
            The distribution of the sum.
        """
        return self.pure(other).combine(self, operator.add)

    def __sub__(self, other: "Distribution[T] | T") -> "Distribution[T]":
        """``a - b`` — the signed difference of independent draws, or a shift down.

        The everyday use is a constant less a distribution: survivors are
        ``size - casualties``, one quantity read off the other with nothing
        random on the left.

        Differencing two *distributions* is the narrower case, and it is only a
        lead when the two are genuinely unrelated. It is the wrong tool for the
        score of a combat, where the sides are correlated: the volley that thins
        one of them scores for the other, so the two counts move together and
        their joint cannot be recovered from the marginals. Build that joint
        where the correlation is known. See :meth:`combine`.

        Returns:
            The distribution of the difference.
        """
        return self.combine(self._lifted(other), operator.sub)

    def __rsub__(self, other: T) -> "Distribution[T]":
        """``value - dist`` — a constant less this distribution.

        As with :meth:`__radd__`, ``other`` is always a bare outcome. The
        operands stay in written order.

        Returns:
            The distribution of the difference.
        """
        return self.pure(other).combine(self, operator.sub)

    def __floordiv__(self, group_size: int) -> "Distribution[T]":
        """``dist // n`` — floor-divide every outcome, merging those that land together.

        A count collapses into whole groups of ``n``. Unsaved wounds accumulate
        into slain multi-Wound models this way, the remainder sitting on a
        survivor, so several wound counts mean the same casualty count.

        The divisor is a fixed group size, not a distribution: dividing by a
        random quantity has no meaning here, and ``n`` of zero or less has no
        group to count. Both are rejected rather than left to fail inside the
        fold, matching :func:`avelorn.core.dice.group_distribution`.

        Returns:
            The distribution of the quotient.

        Raises:
            ValueError: ``group_size`` is less than 1.
        """
        if group_size < 1:
            raise ValueError("group_size must be >= 1")
        return self.map(lambda outcome: operator.floordiv(outcome, group_size))

    def __rmatmul__(self, copies: int) -> "Distribution[T]":
        """``n @ dist`` — the sum of ``n`` independent copies of this distribution.

        The repeat, kept distinct from any scaling of the outcomes themselves:
        ``3 @ dist`` resolves the same quantity three times over and totals it,
        which is not the same distribution as tripling one draw. Only this
        direction is defined, so the two cannot be confused.

        Zero copies has no answer for a general outcome type — there is no
        outcome meaning "nothing yet" to start from — so a caller wanting it
        names the identity itself with :meth:`pure`.

        Being repeated ``+``, this inherits its meaning of "sum" from the outcome
        type, and the tuple-concatenation trap in :meth:`__add__` with it.

        It is also repeated ``+`` in cost: ``copies`` convolutions, each over a
        support that grows as it goes, so the work is quadratic in ``copies``.
        For the one case with a closed form — n independent successes, where the
        answer is the binomial — :func:`avelorn.core.dice.binomial_distribution`
        gives the same masses far more cheaply (identical to floating error;
        measured at 33x faster at n=10 and 190x at n=80). Prefer it on the wide
        volleys, where the count is large and reached inside a loop.

        Returns:
            The distribution of the total over ``copies`` draws.

        Raises:
            ValueError: ``copies`` is less than 1.
        """
        if copies < 1:
            raise ValueError("copies must be >= 1")
        total = self
        for _ in range(copies - 1):
            total = total + self
        return total

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


@dataclass(frozen=True)
class Step[T: Hashable, U: Hashable]:
    """One stochastic step, ``T -> Distribution[U]``, as a value.

    A :meth:`Distribution.bind` argument that can be named, stored, and
    composed *before* any distribution reaches it: ``a >> b`` builds the
    two-step chain, and applying it to a distribution runs the whole thing.
    That makes a resolution sequence assemblable as data — one edge per step —
    rather than only spellable as nested calls.
    """

    resolve: Callable[[T], Distribution[U]]

    @classmethod
    def certain(cls, relabel: Callable[[T], U]) -> "Step[T, U]":
        """Lift a deterministic ``relabel`` into a step that mixes nothing.

        How a plain change of variable joins a chain of stochastic steps, so
        :meth:`Distribution.map` needs no operator of its own.

        Returns:
            The step whose every outcome is a point mass on ``relabel``'s image.
        """
        return cls(lambda outcome: Distribution.pure(relabel(outcome)))

    def __call__(self, outcome: T) -> Distribution[U]:
        """Resolve the step at one outcome.

        Returns:
            The distribution this step reaches from ``outcome``.
        """
        return self.resolve(outcome)

    def __rshift__[V: Hashable](self, then: Callable[[U], Distribution[V]]) -> "Step[T, V]":
        """``a >> b`` composes two steps into the single step "a, then b".

        Associative, so a chain of any length composes in any grouping and
        resolves the same (checked in the tests).

        Returns:
            The composed step from this one's input to ``then``'s output.
        """
        return Step(lambda outcome: self.resolve(outcome).bind(then))
