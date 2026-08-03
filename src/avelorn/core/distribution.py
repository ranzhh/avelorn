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
        """Feed this distribution into ``step``, which is :meth:`bind`.

        It reads left to right, in the order the engine resolves: a distribution,
        then the step it flows into. ``step`` is any callable of that shape, so a
        plain function and a :class:`Step` both chain.

        Returns:
            The mixed distribution over the downstream outcomes.
        """
        return self.bind(step)

    def combine[U: Hashable, V: Hashable](
        self, other: "Distribution[U]", op: Callable[[T, U], V]
    ) -> "Distribution[V]":
        """Apply ``op`` to **independent** draws from this distribution and ``other``.

        Every arithmetic operator below is written in terms of this. It takes the
        joint of two unrelated variables and relabels each pair by ``op``. It is
        built on :meth:`bind` and :meth:`map`, so it adds no second fold.

        Independence is an assumption about the two arguments, and this cannot
        check it. Two sides of one combat are correlated, because the volley that
        thins one of them scores for the other. Build that joint where the
        correlation is known. It cannot be recovered from marginals here.

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
        """Sum independent draws, or shift every outcome by a constant.

        A distribution on the right gives the convolution: the total of two
        unrelated quantities, a second volley's casualties on top of the first. A
        bare outcome on the right shifts every value by that constant, which is
        how a fixed edge such as a Rank Bonus enters a distribution of leads.

        The sum is whatever ``+`` means for the outcome type, so it is a total
        only for numbers. On a tuple outcome, such as the vector of per-class
        counts the multinomial aggregation produces, ``+`` concatenates instead.
        The result is longer tuples, not component sums, and nothing raises. Use
        :meth:`combine` with an explicit component-wise operation for those; the
        module docstring has the detail.

        Returns:
            The distribution of the sum.
        """
        return self.combine(self._lifted(other), operator.add)

    def __radd__(self, other: T) -> "Distribution[T]":
        """Sum a constant on the left with this distribution.

        Python only reaches a reflected operator when the left operand is of
        another type, so ``other`` is always a bare outcome here, never a
        distribution. The constant stays on the left, so a ``+`` that does not
        commute still means what it reads as.

        Returns:
            The distribution of the sum.
        """
        return self.pure(other).combine(self, operator.add)

    def __sub__(self, other: "Distribution[T] | T") -> "Distribution[T]":
        """Take the signed difference of independent draws, or shift down by a constant.

        The everyday use is a constant less a distribution. Survivors are
        ``size - casualties``, one quantity read off the other, with nothing
        random on the left.

        Differencing two *distributions* is the narrower case, and it is a lead
        only when the two are genuinely unrelated. It is the wrong tool for the
        score of a combat. There the sides are correlated: the volley that thins
        one of them scores for the other, so the two counts move together and
        their joint cannot be recovered from the marginals. Build that joint
        where the correlation is known. See :meth:`combine`.

        Returns:
            The distribution of the difference.
        """
        return self.combine(self._lifted(other), operator.sub)

    def __rsub__(self, other: T) -> "Distribution[T]":
        """Subtract this distribution from a constant.

        As with :meth:`__radd__`, ``other`` is always a bare outcome. The
        operands stay in written order.

        Returns:
            The distribution of the difference.
        """
        return self.pure(other).combine(self, operator.sub)

    def __floordiv__(self, group_size: int) -> "Distribution[T]":
        """Floor-divide every outcome, merging those that land together.

        A count collapses into whole groups of ``group_size``. Unsaved wounds
        accumulate into slain multi-Wound models this way, the remainder sitting
        on a survivor, so several wound counts mean the same casualty count.

        The divisor is a fixed group size, not a distribution. Dividing by a
        random quantity has no meaning here, and a size below 1 has no group to
        count. Both are rejected up front rather than left to fail inside the
        fold, which matches :func:`avelorn.core.dice.group_distribution`.

        Returns:
            The distribution of the quotient.

        Raises:
            ValueError: ``group_size`` is less than 1.
        """
        if group_size < 1:
            raise ValueError("group_size must be >= 1")
        return self.map(lambda outcome: operator.floordiv(outcome, group_size))

    def __rmatmul__(self, copies: int) -> "Distribution[T]":
        """Sum ``copies`` independent copies of this distribution.

        This is the repeat, and it is kept distinct from any scaling of the
        outcomes. ``3 @ dist`` resolves the same quantity three times and totals
        it, which is a different distribution from tripling one draw. Only this
        direction is defined, so the two cannot be confused.

        Zero copies has no answer for a general outcome type, because there is no
        outcome meaning "nothing yet" to start from. A caller wanting one names
        that identity itself with :meth:`pure`.

        Being repeated ``+``, this takes its meaning of "sum" from the outcome
        type, and the tuple-concatenation trap in :meth:`__add__` with it.

        It is repeated ``+`` in cost too: one convolution per copy, each over a
        support that grows as it goes, so the work is quadratic in ``copies``.
        One case has a closed form. For n independent successes the answer is the
        binomial, and :func:`avelorn.core.dice.binomial_distribution` gives the
        same masses far more cheaply, identical to floating error and measured at
        33x faster at n=10 and 190x at n=80. Prefer it on the wide volleys, where
        the count is large and reached inside a loop.

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
    """Hold one stochastic step, ``T -> Distribution[U]``, as a value.

    This is a :meth:`Distribution.bind` argument that can be named, stored, and
    composed *before* any distribution reaches it. ``a >> b`` builds the two-step
    chain, and applying it to a distribution runs the whole thing. A resolution
    sequence can then be assembled as data, one edge per step, instead of only
    being spellable as nested calls.
    """

    resolve: Callable[[T], Distribution[U]]

    @classmethod
    def certain(cls, relabel: Callable[[T], U]) -> "Step[T, U]":
        """Lift a deterministic ``relabel`` into a step that mixes nothing.

        This is how a plain change of variable joins a chain of stochastic steps,
        which is why :meth:`Distribution.map` needs no operator of its own.

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
        """Compose two steps into the single step "this one, then ``then``".

        Composition is associative, so a chain of any length groups any way and
        resolves the same. The tests check that.

        Returns:
            The composed step from this one's input to ``then``'s output.
        """
        return Step(lambda outcome: self.resolve(outcome).bind(then))
