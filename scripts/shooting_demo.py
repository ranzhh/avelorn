"""Two units shoot one target — and their tolls compose in a single line.

Elven Archers and Sisters of Avelorn both fire at a block of Elven Spearmen.
Two units shooting one target resolve one after the other, casualties removed
between, so the Sisters shoot whatever the Archers leave standing. Composing the
two is one ``bind`` — shoot the survivors of the first with the second. Chain a
third unit and it is just another bind.

Resolved exactly, no dice rolled, no arguments — run it and read the numbers.
"""

from avelorn.core.distribution import Distribution
from avelorn.tow.game import TOWGame


def main() -> None:
    """Field two shooters and a target, compose their volleys, print the toll."""
    game = TOWGame.load_data()
    target = game.units["elven-spearmen"]
    size = 20
    archers = game.field(game.units["elven-archers"], 10)
    sisters = game.field(game.units["sisters-of-avelorn"], 10)

    def survivors(shooters, standing):
        # Spearmen left standing after `shooters` fire at `standing` of them.
        if standing == 0:
            return Distribution.pure(0)
        volley = game.shooting.volley(shooters, game.field(target, standing), distance=12)
        return Distribution.from_counts(volley.casualties).map(lambda dead: standing - dead)

    # The whole point: two units' fire composes in one line — the Sisters shoot
    # whatever the Archers leave standing.
    left = survivors(archers, size).bind(lambda standing: survivors(sisters, standing))
    casualties = left.map(lambda standing: size - standing)

    def toll(shooters):  # one unit's casualties alone, for comparison
        return survivors(shooters, size).map(lambda standing: size - standing)

    print(f"{size} Elven Spearmen under fire — expected casualties:")
    print(f"  Elven Archers alone:       {toll(archers).expect(float):.2f}")
    print(f"  Sisters of Avelorn alone:  {toll(sisters).expect(float):.2f}")
    print(f"  both, composed:            {casualties.expect(float):.2f}")
    print(f"  P(at least one falls):     {casualties.prob(lambda k: k >= 1):.3f}")
    print(f"  P(five or more fall):      {casualties.prob(lambda k: k >= 5):.3f}")


if __name__ == "__main__":
    main()
