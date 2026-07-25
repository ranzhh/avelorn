"""Prototype: the demos' hand-folds collapse onto the Distribution monad.

The merged ``bow_of_avelorn_demo`` folds an opening volley into a combat by
hand — ``sum(p * win_given_charge(...) for k, p in enumerate(...))``. That sum
is :meth:`Distribution.bind`. This spike reproduces the same numbers through
the monad, so the fold reads as a pipeline (map → bind → prob) instead of an
enumerate-and-sum, and shows the shooting-query collapse alongside.

Run: uv run python scripts/distribution_prototype.py
"""

from enum import Enum, auto

from avelorn.core.distribution import Distribution
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot


class Side(Enum):
    """Who won the combat — the outcome type the fold produces."""

    CHARGER = auto()
    DRAW = auto()
    DEFENDER = auto()


def win_distribution(game: TOWGame, defender, charging: int, models: int, distance: int):
    """The combat's winner as a Distribution[Side] when ``charging`` Lions charge.

    A stochastic step ``survivors -> Distribution[Side]`` — exactly the arrow
    ``bind`` wants. Scoring stays inside this one combat (the Stand & Shoot is
    its reaction); the opening volley composes from outside.

    Returns:
        A distribution over who wins the combat.
    """
    if charging == 0:
        return Distribution.pure(Side.DEFENDER)  # nothing arrives to fight
    lions = game.field(game.units["white-lions-of-chrace"], charging).wielding(
        "Chracian Great Blade"
    )
    unit = game.field(defender, models).wielding("Hand Weapon")
    turn = game.turn()
    with turn.movement() as movement:
        engagement = movement.charge(lions, unit, Charge(distance, ChargeArc.FRONT))
        engagement.react(StandAndShoot())
    with turn.combat() as combat:
        scored = combat.result(combat.fight(engagement))
    return Distribution(
        {Side.CHARGER: scored.p_a_wins, Side.DRAW: scored.p_draw, Side.DEFENDER: scored.p_b_wins}
    )


def _defender_wins(side: Side) -> bool:
    return side is Side.DEFENDER


def analyse(game: TOWGame, defender, models: int, distance: int) -> None:
    """Fold one unit's opening volley into the combat, through the monad, and print."""
    with game.turn().shooting() as shooting:
        opening = shooting.volley(
            game.field(defender, models),
            game.field(game.units["white-lions-of-chrace"], models),
            distance=distance,
        )

    # The fold, as a pipeline. `opening.casualties` is a count-pmf; lift it,
    # relabel felled -> survivors, bind the combat onto each, read off P(win).
    def combat(survivors: int) -> Distribution[Side]:
        return win_distribution(game, defender, survivors, models, distance)

    p_win = (
        Distribution.from_counts(opening.casualties)
        .map(lambda felled: models - felled)
        .bind(combat)
        .prob(_defender_wins)
    )
    p_dont = combat(models).prob(_defender_wins)

    # The shooting-query collapse: prob/expect replace the query layer and
    # expected_value, on the same lifted distribution.
    felled = Distribution.from_counts(opening.casualties)
    mean, any_kill = felled.expect(float), felled.prob(lambda k: k >= 1)
    print(f"{defender.name}:")
    print(f"  volley fells: mean {mean:.2f}, P(>=1) {any_kill:.3f}")
    print(f"  P(win) — shoot elsewhere {p_dont:.3f}, shoot the Lions {p_win:.3f}")


def main() -> None:
    """Reproduce the bow fold through the monad for both units."""
    game = TOWGame.load_data()
    for slug in ("sisters-of-avelorn", "elven-archers"):
        analyse(game, game.units[slug], models=10, distance=10)


if __name__ == "__main__":
    main()
