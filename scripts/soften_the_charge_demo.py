"""Same charge, two different units — should you shoot the chargers first?

You are the High Elf player. A unit of White Lions of Chrace is 10" away and
will charge next turn whatever you do. This turn you can loose your unit's
volley at those Lions, or at some other target. Either way the Lions charge,
your unit Stand & Shoots as they come, and the lines fight. So: *does shooting
the Lions first raise your chance of winning that combat, and by how much?*

Ask it of two units in the same spot — **Sisters of Avelorn** and **Elven
Archers** — and the same tactic gives opposite advice. The Sisters both shoot
well (the Bow of Avelorn is magical, so a White Lion's Lion Cloak cannot better
its save) and hold the line (Strike First, armour, and a magical Stand & Shoot
that scores for them), so thinning the charge flips a fight they would lose into
one they win. The Archers do neither: a plain longbow lets the Lion Cloak stand,
so they fell far fewer, and with WS 4, no Strike First and no armour they lose
the melee whether they shot first or not — their arrows are better spent on a
softer target.

The point of the toolkit is that this is answered by folding **distributions**,
not by rounding to an average. The opening volley does not fell "about three"
Lions — it fells a whole spread. Each outcome leads to a different charge, and
each charge to a different combat. The answer folds every branch, weighted by
how likely it is — :meth:`Distribution.bind` — instead of an enumerate-and-sum:

    win = felled.map(survivors).bind(combat).prob(defender_wins)

The Stand & Shoot inside each branch is folded natively — ``fight`` enters the
charger already thinned by the reaction and scores its wounds toward the combat
result. The opening volley is a *previous* turn, so its wounds must not score
this combat; it only changes how many Lions arrive. That is why it is folded
here by ``bind`` over the surviving-charger count rather than handed to ``fight``
as prior losses (which would score it). Letting a unit enter a combat
thinned-but-unscored is the one piece the engine still lacks.

Usage: uv run python scripts/soften_the_charge_demo.py [models] [distance]
       (keep distance within a charge's reach — a unit's Movement plus 6")

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging
from enum import Enum, auto

from avelorn.core.distribution import Distribution
from avelorn.core.logging import configure_logging
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot
from avelorn.tow.schema.unit import Characteristic, Unit


class Side(Enum):
    """Who won the combat — the outcome the fold produces."""

    CHARGER = auto()
    DRAW = auto()
    DEFENDER = auto()


def _defender_wins(side: Side) -> bool:
    return side is Side.DEFENDER


def win_distribution(
    game: TOWGame, defender: Unit, models: int, charging: int, distance: int
) -> Distribution[Side]:
    """Who wins when ``charging`` White Lions charge ``models`` defenders.

    A stochastic step ``charging -> Distribution[Side]`` — exactly the arrow
    :meth:`Distribution.bind` composes. Resolves the charge, the defender's
    Stand & Shoot (which thins the chargers and scores for the defender, folded
    natively), and the melee. Scoring stays inside this one combat; a prior
    turn's opening volley is folded from outside.

    Returns:
        The distribution over who wins; a point mass on the defender when
        nothing arrives to charge.
    """
    if charging == 0:
        return Distribution.pure(Side.DEFENDER)
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


def win_if_shot(game: TOWGame, defender: Unit, models: int, distance: int):
    """The defender's opening volley, and P(win) with its distribution folded in.

    Lift the volley's casualty pmf, relabel felled -> surviving chargers, bind
    the combat onto each survivor count, and read off P(defender wins). Every
    branch is resolved exactly and mixed by likelihood — no averaging.

    Returns:
        The opening :class:`ShootingResult` and the folded P(defender wins).
    """
    lions = game.units["white-lions-of-chrace"]
    with game.turn().shooting() as shooting:
        opening = shooting.volley(
            game.field(defender, models), game.field(lions, models), distance=distance
        )

    def combat(charging: int) -> Distribution[Side]:
        return win_distribution(game, defender, models, charging, distance)

    folded = (
        Distribution.from_counts(opening.casualties)
        .map(lambda felled: models - felled)
        .bind(combat)
        .prob(_defender_wins)
    )
    return opening, folded


def _pmf(casualties: list[float]) -> str:
    # The opening volley's casualty distribution, compactly — the thing we fold.
    return "  ".join(f"{k}:{p:.0%}" for k, p in enumerate(casualties) if p > 0.005)


def _report(defender: Unit, opening, dont: float, shoot: float, models: int) -> None:
    ballistic_skill = defender.profiles[0][Characteristic.BALLISTIC_SKILL]
    print(
        f"  {defender.name} (BS {ballistic_skill}, {opening.shots}-shot volley, "
        f"Lions save {opening.save_target}+):"
    )
    print(f"    opening volley fells (of {models}):  {_pmf(opening.casualties)}")
    print(f"    shoot elsewhere — Lions charge at full strength:  P(win) {dont:.3f}")
    print(
        f"    shoot the Lions first (volley folded in):         P(win) {shoot:.3f}"
        f"   ({shoot - dont:+.3f})"
    )


def main() -> None:
    """Parse argv, fold each unit's opening volley into the combat, print the verdict."""
    parser = argparse.ArgumentParser(
        description="Same White Lion charge, two units: should you shoot the chargers first?"
    )
    parser.add_argument("models", nargs="?", type=int, default=10, help="models on each side")
    parser.add_argument(
        "distance",
        nargs="?",
        type=int,
        default=10,
        help="inches the Lions stand off — the opening shot's range and the charge",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="emit the DEBUG math trace to stderr"
    )
    args = parser.parse_args()
    if args.verbose:
        configure_logging(logging.DEBUG)

    game = TOWGame.load_data()

    print(
        f"{args.models} White Lions of Chrace will charge next turn "
        f'({args.distance}"). Two High Elf\nunits face them; each can shoot the Lions first, '
        "or shoot elsewhere. P(win the\nensuing combat), each opening volley's whole "
        "casualty distribution folded in:\n"
    )

    for slug in ("sisters-of-avelorn", "elven-archers"):
        defender = game.units[slug]
        opening, shoot = win_if_shot(game, defender, args.models, args.distance)
        dont = win_distribution(game, defender, args.models, args.models, args.distance).prob(
            _defender_wins
        )
        _report(defender, opening, dont, shoot, args.models)
        print()

    print(
        "  verdict: same board, same threat, opposite advice. The Sisters both shoot well\n"
        "  (a magical bow the Lion Cloak can't stop) and hold the line (Strike First, armour,\n"
        "  and a Stand & Shoot that scores for them), so thinning the charge flips a fight\n"
        "  they would lose into one they win — shoot the Lions. The Archers do neither: a\n"
        "  plain longbow lets the cloak stand, so they fell far fewer, and WS 4 with no armour\n"
        "  and no Strike First loses the melee whether they shot first or not. Their arrows\n"
        "  are better spent on a target they can actually break."
    )


if __name__ == "__main__":
    main()
