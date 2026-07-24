"""How much of the Sisters' edge is the Bow of Avelorn itself?

White Lions of Chrace charge Sisters of Avelorn. The Sisters loose one volley
of the Bow of Avelorn as a Stand & Shoot reaction as the Lions close, then the
two lines meet in close combat. The turn is walked phase by phase, as the
rulebook plays it: the charge and its reaction are a Movement-phase event; the
melee is fought in the Combat phase.

Then the counterfactual: what if the Sisters carried an ordinary bow? The
datasheet is the single source of truth, so the swap is a one-line edit — trade
the printed Bow of Avelorn for a Warbow, re-field, and re-ask the same
questions. The difference between the two runs is exactly what the Bow of
Avelorn is worth, and it decomposes into two printed things the ordinary bow
lacks:

- **Magical Attacks.** The Bow of Avelorn's arrows are magical, so a White
  Lion's Lion Cloak — which betters its save by one against *non-magical*
  shooting — is turned off. Against the magical bow the Lions save on 6+;
  against the ordinary bow the cloak wakes up and they save on 5+.
- **A second Armour Bane (1).** The Sisters' Arrows of Isha already grants any
  bow they carry Armour Bane (1); the Bow of Avelorn prints its own on top, so
  a natural 6 To Wound improves Armour Piercing by two, not one. The Warbow
  keeps only the granted instance.

Resolved exactly, no dice rolled. Prints each run's Stand & Shoot volley and
melee odds, then the side-by-side verdict.

Usage: uv run python scripts/bow_of_avelorn_demo.py [models] [charge_inches]

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging

from avelorn.core.dice import expected_value
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


def resolve(game: TOWGame, sisters, lions_unit, models: int, inches: int):
    """Walk one Lions-into-Sisters turn and return the volley and scored melee.

    ``sisters`` is a datasheet (the printed one, or a rearmed copy); the Lions
    are fielded fresh each time so the two runs differ only by the Sisters' bow.

    Returns:
        The Stand & Shoot volley (or None) and the scored combat result.
    """
    lions = game.field(lions_unit, models).wielding("Chracian Great Blade")
    defenders = game.field(sisters, models).wielding("Hand Weapon")

    turn = game.turn()
    with turn.movement() as movement:
        # The Lions charge; the Sisters hold their hand weapon for the melee to
        # come and Stand & Shoot with their sole missile weapon as the reaction.
        engagement = movement.charge(lions, defenders, Charge(inches, ChargeArc.FRONT))
        volley = engagement.react(StandAndShoot())
    with turn.combat() as combat:
        scored = combat.result(combat.fight(engagement))
    return volley, scored


def _report(label: str, volley, scored, models: int) -> None:
    print(f"  {label}:")
    if volley is None:
        print("    Stand & Shoot: no volley")
    else:
        felled = expected_value(volley.casualties)
        print(
            f"    Stand & Shoot: Lions save on {volley.save_target}+, "
            f"{felled:.2f} of {models} fall before contact"
        )
    print(
        f"    melee: P(Sisters win) {scored.p_b_wins:.3f}   "
        f"P(draw) {scored.p_draw:.3f}   P(Lions win) {scored.p_a_wins:.3f}"
    )


def main() -> None:
    """Parse argv, resolve the bow and its counterfactual, and print the verdict."""
    parser = argparse.ArgumentParser(
        description="How much of the Sisters' edge is the Bow of Avelorn itself?"
    )
    parser.add_argument("models", nargs="?", type=int, default=10, help="models on each side")
    parser.add_argument(
        "charge_inches", nargs="?", type=int, default=8, help="inches the Lions charged"
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

    print(
        f"{args.models} White Lions of Chrace charge {args.models} Sisters of Avelorn "
        f'({args.charge_inches}")\n'
    )

    # The printed Sisters, and a counterfactual copy carrying an ordinary bow.
    bow_volley, bow_scored = resolve(game, sisters, lions, args.models, args.charge_inches)
    ordinary = rearm(sisters, "Bow of Avelorn", "Warbow")
    warbow_volley, warbow_scored = resolve(game, ordinary, lions, args.models, args.charge_inches)

    _report("Bow of Avelorn (as printed)", bow_volley, bow_scored, args.models)
    print()
    _report("an ordinary Warbow", warbow_volley, warbow_scored, args.models)

    lift = expected_value(bow_volley.casualties) - expected_value(warbow_volley.casualties)
    print(
        "\n  verdict: the Bow of Avelorn is worth its name. Its Magical Attacks turn\n"
        "  off Lion Cloak — the Lions weather it on 6+, not the 5+ an ordinary bow\n"
        f"  leaves them — and its printed Armour Bane stacks with Arrows of Isha. Across\n"
        f"  the volley that is +{lift:.2f} chargers felled, and it carries into the melee:\n"
        f"  the Sisters win {bow_scored.p_b_wins:.3f} of the time with it, "
        f"{warbow_scored.p_b_wins:.3f} without."
    )


if __name__ == "__main__":
    main()
