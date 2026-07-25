"""Shoot the chargers first? Fold the opening volley into the ensuing combat.

White Lions charge next turn regardless. Shooting them first folds the volley's
whole casualty distribution into the melee (one `bind`) — decisive for the
Sisters of Avelorn, near-useless for plain Elven Archers.
"""

from enum import Enum, auto

from avelorn.core.distribution import Distribution
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot
from avelorn.tow.schema.unit import Characteristic, Unit


class Side(Enum):
    """Who wins the combat."""

    CHARGER, DRAW, DEFENDER = auto(), auto(), auto()


def _defender_wins(side: Side) -> bool:
    return side is Side.DEFENDER


def win(game: TOWGame, defender: Unit, charging: int) -> Distribution[Side]:
    """Who wins when ``charging`` White Lions charge, as a Distribution[Side].

    Returns:
        The distribution over the combat's winner.
    """
    if charging == 0:
        return Distribution.pure(Side.DEFENDER)
    lions = game.field(game.units["white-lions-of-chrace"], charging).wielding(
        "Chracian Great Blade"
    )
    unit = game.field(defender, 10).wielding("Hand Weapon")
    turn = game.turn()
    with turn.movement() as movement:
        engagement = movement.charge(lions, unit, Charge(10, ChargeArc.FRONT))
        engagement.react(StandAndShoot())
    with turn.combat() as combat:
        r = combat.result(combat.fight(engagement))
    return Distribution({Side.CHARGER: r.p_a_wins, Side.DRAW: r.p_draw, Side.DEFENDER: r.p_b_wins})


def win_if_shot(game: TOWGame, defender: Unit):
    """The opening volley, and P(defender wins) with its distribution folded in.

    Returns:
        The opening ShootingResult and the folded P(defender wins).
    """
    lions = game.units["white-lions-of-chrace"]
    with game.turn().shooting() as shooting:
        opening = shooting.volley(game.field(defender, 10), game.field(lions, 10), distance=10)
    folded = (
        Distribution.from_counts(opening.casualties)
        .map(lambda felled: 10 - felled)
        .bind(lambda standing: win(game, defender, standing))
        .prob(_defender_wins)
    )
    return opening, folded


def _report(defender: Unit, opening, dont: float, shoot: float) -> None:
    bs = defender.profiles[0][Characteristic.BALLISTIC_SKILL]
    fells = "  ".join(f"{k}:{p:.0%}" for k, p in enumerate(opening.casualties) if p > 0.005)
    print(f"  {defender.name} (BS {bs}, Lions save {opening.save_target}+):")
    print(f"    opening volley fells (of 10):  {fells}")
    print(f"    shoot elsewhere:       P(win) {dont:.3f}")
    print(f"    shoot the Lions first: P(win) {shoot:.3f}   ({shoot - dont:+.3f})")


def main() -> None:
    """Fold each unit's opening volley into the combat and print P(win)."""
    game = TOWGame.load_data()
    print('10 White Lions charge next turn (10"). Shoot them first?\n')
    for slug in ("sisters-of-avelorn", "elven-archers"):
        defender = game.units[slug]
        opening, shoot = win_if_shot(game, defender)
        dont = win(game, defender, 10).prob(_defender_wins)
        _report(defender, opening, dont, shoot)
        print()


if __name__ == "__main__":
    main()
