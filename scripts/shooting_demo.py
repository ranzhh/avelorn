"""Two units shoot one target -- and their volleys compose into a single value.

Elven Archers and Sisters of Avelorn both fire at a block of Elven Spearmen.
Two units shooting one target resolve one after the other, casualties removed
between, so the Sisters shoot whatever the Archers leave standing.

Each unit's fire is a step: standing spearmen in, standing spearmen out.
`bind` chains one onto the distribution the last one left, so adding a third
shooter is one more `bind`. Survivors read as `standing - casualties` and the
toll as `size - survivors`, because a distribution subtracts like the number it
stands for.

Resolved exactly -- the per-shot probability below is a true fraction, not a
rounding of one. No dice rolled, no arguments: run it and read the numbers.
"""

from fractions import Fraction

from avelorn.core.distribution import Distribution, Kernel
from avelorn.tow.contingent import Contingent
from avelorn.tow.game import TOWGame


def main() -> None:
    """Field two shooters and a target, compose their volleys, print the toll."""
    game = TOWGame.load_data()
    target = game.units["elven-spearmen"]
    size = 20
    archers = game.field(game.units["elven-archers"], 10)
    sisters = game.field(game.units["sisters-of-avelorn"], 10)

    def fire(shooters: Contingent) -> Kernel[int]:
        # One unit's volley as a step: spearmen standing -> spearmen still standing.
        def volley(standing: int) -> Distribution[int]:
            if standing == 0:
                return Distribution.pure(0)
            fired = game.shooting.volley(shooters, game.field(target, standing), distance=12)
            return standing - Distribution.from_counts(fired.casualties)

        return volley

    # The whole point: two units' fire is one chain, each step fed the last one's spread.
    standing = Distribution.pure(size).bind(fire(archers)).bind(fire(sisters))
    casualties = size - standing

    def toll(shooters: Contingent) -> Distribution[int]:  # one unit alone, for comparison
        return size - Distribution.pure(size).bind(fire(shooters))

    lone = game.shooting.volley(archers, game.field(target, size), distance=12)

    print(f"{size} Elven Spearmen under fire -- expected casualties:")
    print(f"  Elven Archers alone:       {toll(archers).expect(Fraction):.2f}")
    print(f"  Sisters of Avelorn alone:  {toll(sisters).expect(Fraction):.2f}")
    print(f"  both, composed:            {casualties.expect(Fraction):.2f}")
    print(f"  P(at least one falls):     {casualties.prob(lambda k: k >= 1):.3f}")
    print(f"  P(five or more fall):      {casualties.prob(lambda k: k >= 5):.3f}")
    print()
    print(f"  an Archer's shot wounds:   {lone.p_unsaved} exactly")
    print(f"  the toll sums to:          {casualties.total()} exactly")


if __name__ == "__main__":
    main()
