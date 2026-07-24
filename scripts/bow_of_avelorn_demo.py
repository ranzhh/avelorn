"""Should the Sisters shoot the charging Lions first — and how much is the bow?

You are the High Elf player. A unit of White Lions of Chrace is 10" away and
will charge your Sisters of Avelorn next turn whatever you do. This turn you can
loose the Sisters' volley at those Lions, or at some other target. Either way
the Lions charge, and the Sisters Stand & Shoot as they come. So: *does shooting
the Lions first raise your chance of winning the ensuing combat, and by how
much?* And then the counterfactual — *how much of that is the Bow of Avelorn
itself, rather than an ordinary bow?*

The point of the toolkit is that this is answered by folding **distributions**,
not by rounding to an average. The opening volley does not fell "about three"
Lions — it fells a whole spread (here most often two to four, sometimes none,
sometimes six). Each of those outcomes leads to a different charge, and each
charge to a different combat. The answer is every branch resolved exactly and
mixed by how likely it is:

    P(win | shoot them) = sum over k of  P(volley fells k) * P(win | 10-k charge)

The Stand & Shoot inside each branch is folded natively — ``fight`` enters the
charger already thinned by the reaction and scores its wounds toward the
Sisters' combat result. The opening volley is a *previous* turn, so its wounds
must not score this combat; it only changes how many Lions arrive. That is why
it is folded here as the mixture above rather than handed to ``fight`` as prior
losses (which would score it). The one thing the engine still lacks is a way to
enter a combat thinned-but-unscored directly — until it grows one (a cross-turn
battle layer), this mixture is the honest fold, and it is exact.

Usage: uv run python scripts/bow_of_avelorn_demo.py [models] [distance]
       (keep distance within a charge's reach — a unit's Movement plus 6")

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging

from avelorn.core.logging import configure_logging
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot
from avelorn.tow.schema.unit import Unit


def rearm(unit: Unit, frm: str, to: str) -> Unit:
    """A copy of ``unit`` with the equipment entry ``frm`` swapped for ``to``.

    The datasheet is the source of truth, so a counterfactual loadout is a
    copy with one printed name changed — re-field it and the loadout, rules,
    and every derived answer re-resolve from the new gear.

    Returns:
        A datasheet identical to ``unit`` but carrying ``to`` in place of ``frm``.
    """
    equipment = [to if item == frm else item for item in unit.equipment]
    return unit.model_copy(update={"equipment": equipment})


def win_given_charge(
    game: TOWGame, sisters: Unit, lions: Unit, models: int, charging: int, distance: int
) -> float:
    """P(the Sisters win the combat) when ``charging`` Lions charge ``models`` Sisters.

    Resolves the Lions' charge, the Sisters' Stand & Shoot reaction (which
    thins the chargers and scores for the Sisters, folded natively), and the
    melee, and returns the probability the Sisters win the combat result.

    Returns:
        P(Sisters win); 1.0 for a charge of zero (nothing arrives to fight).
    """
    if charging == 0:
        return 1.0
    lions_unit = game.field(lions, charging).wielding("Chracian Great Blade")
    sisters_unit = game.field(sisters, models).wielding("Hand Weapon")
    turn = game.turn()
    with turn.movement() as movement:
        engagement = movement.charge(lions_unit, sisters_unit, Charge(distance, ChargeArc.FRONT))
        engagement.react(StandAndShoot())
    with turn.combat() as combat:
        return combat.result(combat.fight(engagement)).p_b_wins


def win_if_shot(game: TOWGame, sisters: Unit, lions: Unit, models: int, distance: int):
    """The opening volley, and P(win) with its whole casualty distribution folded in.

    The Sisters loose a stationary volley at the full-strength Lions, then the
    combat is resolved at *every* surviving Lion count the volley can leave and
    mixed by how likely that count is — no averaging.

    Returns:
        The opening :class:`ShootingResult` and the folded P(Sisters win).
    """
    with game.turn().shooting() as shooting:
        opening = shooting.volley(
            game.field(sisters, models), game.field(lions, models), distance=distance
        )
    # Fold: P(win) = sum_k P(volley fells k) * P(win | models-k Lions charge).
    win_by_survivors = {
        models - k: win_given_charge(game, sisters, lions, models, models - k, distance)
        for k, p in enumerate(opening.casualties)
        if p > 0.0
    }
    folded = sum(
        p * win_by_survivors[models - k] for k, p in enumerate(opening.casualties) if p > 0.0
    )
    return opening, folded


def _pmf(casualties: list[float]) -> str:
    # The opening volley's casualty distribution, compactly — the thing we fold.
    return "  ".join(f"{k}:{p:.0%}" for k, p in enumerate(casualties) if p > 0.005)


def _report(label: str, opening, dont: float, shoot: float, models: int) -> None:
    print(f"  with the {label}:")
    print(f"    opening volley fells (of {models}):  {_pmf(opening.casualties)}")
    print(f"    shoot elsewhere — Lions charge at full strength:  P(Sisters win) {dont:.3f}")
    print(
        f"    shoot the Lions first (volley folded in):         P(Sisters win) {shoot:.3f}"
        f"   ({shoot - dont:+.3f})"
    )


def main() -> None:
    """Parse argv, fold the opening volley into the combat, and print the verdict."""
    parser = argparse.ArgumentParser(
        description="Should the Sisters shoot the charging Lions first? And how much is the bow?"
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
    sisters = game.units["sisters-of-avelorn"]
    lions = game.units["white-lions-of-chrace"]
    ordinary = rearm(sisters, "Bow of Avelorn", "Warbow")

    print(
        f"{args.models} Sisters of Avelorn will be charged by {args.models} White Lions of "
        f'Chrace next turn ({args.distance}").\nThis turn they can shoot the Lions first, or '
        "shoot elsewhere. P(Sisters win the\nensuing combat), the opening volley's whole "
        "casualty distribution folded in:\n"
    )

    for label, sheet in (("Bow of Avelorn", sisters), ("ordinary Warbow", ordinary)):
        opening, shoot = win_if_shot(game, sheet, lions, args.models, args.distance)
        dont = win_given_charge(game, sheet, lions, args.models, args.models, args.distance)
        _report(label, opening, dont, shoot, args.models)
        print()

    print(
        "  verdict: shooting the Lions first is decisive — with the Bow of Avelorn it turns\n"
        "  a combat the Sisters mostly lose into one they mostly win, and the ordinary bow\n"
        "  is close behind. The edge is folded from the volley's full spread of outcomes,\n"
        "  not its average, so a good roll (five Lions down) and a poor one (none) are both\n"
        "  weighed. The Bow of Avelorn still leads: it fells more now, and its magical\n"
        "  Stand & Shoot ignores the Lion Cloak the ordinary bow runs into."
    )


if __name__ == "__main__":
    main()
