"""How much of the Sisters' edge is the Bow of Avelorn itself?

Two turns of a Sisters-of-Avelorn-versus-White-Lions fight, resolved exactly:

- The **Sisters' turn**: standing still, they loose a full volley at the
  approaching Lions — every rank fires, Volley Fire and all.
- The **Lions' turn**: the Lions charge; the Sisters loose a second, smaller
  volley as a Stand & Shoot reaction (only the front rank, and at a penalty),
  then the two lines meet in close combat.

Then the counterfactual: what if the Sisters carried an ordinary bow? The
datasheet is the single source of truth, so the swap is a one-line edit — trade
the printed Bow of Avelorn for a Warbow, re-field, and re-ask every question.
The difference between the two runs is exactly what the Bow of Avelorn is
worth, and it decomposes into two printed things the ordinary bow lacks:

- **Magical Attacks.** The Bow of Avelorn's arrows are magical, so a White
  Lion's Lion Cloak — which betters its save by one against *non-magical*
  shooting — is turned off. Against the magical bow the Lions save on 6+;
  against the ordinary bow the cloak wakes up and they save on 5+.
- **A second Armour Bane (1).** The Sisters' Arrows of Isha already grants any
  bow they carry Armour Bane (1); the Bow of Avelorn prints its own on top, so
  a natural 6 To Wound improves Armour Piercing by two, not one. The Warbow
  keeps only the granted instance.

That is a steady proportional edge (~23% more wounds), so its size in wounds
tracks the number of shots: it is roughly twice as large in the full opening
volley as in the five-shot Stand & Shoot, which fires the front rank alone.

The whole point is that the two volleys *combine*. The opening volley thins the
unit that then charges, and the Stand & Shoot thins it again before it strikes,
and together they can break its front rank — which is what turns a fight the
Lions win into one the Sisters win. The Stand & Shoot's casualties carry into
the melee for free (the engine enters the charger already thinned, and those
wounds also count toward the Sisters' combat result). The opening volley's do
not — it is a previous turn, and a prior turn's shooting must not score this
combat — so this demo carries them across the turn **by hand**, removing the
expected number of felled Lions before the charge. That is a deliberately ugly
seam: it rounds a whole distribution down to one integer, where a proper
version would carry the distribution intact. A continuous battle that tracks
casualties across turns is a later layer on top of the engine; this is a
stand-in for it, flagged in the code so no one mistakes it for the real thing.

Usage: uv run python scripts/bow_of_avelorn_demo.py [models] [distance]

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


def resolve(game: TOWGame, sisters, lions_unit, models: int, distance: int):
    """Walk both turns and return the opening volley, reaction, melee, and score.

    ``sisters`` is a datasheet (the printed one, or a rearmed copy); the Lions
    are fielded fresh so the two runs differ only by the Sisters' bow. The Lions
    stand ``distance`` inches off when shot at, and charge that same gap (so keep
    ``distance`` within a charge's reach — a unit's Movement plus 6").

    Returns:
        The Sisters' opening (stationary) volley, the number of Lions it fells,
        their Stand & Shoot reaction as the survivors charge, the fought melee,
        and its scored result.
    """
    lions = game.field(lions_unit, models)
    sisters_fielded = game.field(sisters, models)

    # The Sisters' turn: standing still, they loose a full volley (every rank
    # fires — Volley Fire) at the Lions ``distance`` inches off.
    own_turn = game.turn()
    with own_turn.shooting() as shooting:
        opening = shooting.volley(sisters_fielded, lions, distance=distance)

    # UGLY SEAM — carry the opening volley's casualties across the turn by hand.
    # The engine has no cross-turn casualty state (that is the future Battle
    # layer), and we must NOT route these through the melee's prior-losses: that
    # path credits them to the Sisters' combat result, but a *previous* turn's
    # shooting cannot score *this* combat. So we just remove the expected number
    # of felled Lions before they charge. Crude on purpose — it collapses a whole
    # distribution to one integer. A proper version carries the distribution.
    felled = round(opening.expected_casualties)
    survivors = lions.remove_casualties(felled)

    # The Lions' turn: the survivors charge home with the great blade; the
    # Sisters hold their hand weapon for the melee and Stand & Shoot (front rank
    # only, no Volley Fire, and at a to-hit penalty) as the reaction. That
    # reaction's casualties thin the chargers again before they strike — the
    # engine enters them already thinned — and its wounds score for the Sisters.
    lions_turn = game.turn()
    with lions_turn.movement() as movement:
        engagement = movement.charge(
            survivors.wielding("Chracian Great Blade"),
            sisters_fielded.wielding("Hand Weapon"),
            Charge(distance, ChargeArc.FRONT),
        )
        reaction = engagement.react(StandAndShoot())
    with lions_turn.combat() as combat:
        melee = combat.fight(engagement)
        scored = combat.result(melee)
    return opening, felled, reaction, melee, scored


def _report(label: str, opening, felled: int, reaction, melee, scored, models: int) -> None:
    print(f"  {label}:")
    print(
        f"    opening volley (their turn):    {opening.shots} shots, Lions save "
        f"{opening.save_target}+, {opening.expected_wounds:.2f} wounds "
        f"→ {felled} felled, {models - felled} charge"
    )
    if reaction is None:
        print("    Stand & Shoot (as they charge): no volley")
    else:
        print(
            f"    Stand & Shoot (as they charge): {reaction.shots} shots, Lions save "
            f"{reaction.save_target}+, {reaction.expected_wounds:.2f} wounds"
        )
    print(
        f"    melee casualties:  Lions lose {expected_value(melee.a_casualties):.2f}, "
        f"Sisters lose {expected_value(melee.b_casualties):.2f}"
    )
    print(
        f"    combat result:     P(Sisters win) {scored.p_b_wins:.3f}   "
        f"P(draw) {scored.p_draw:.3f}   P(Lions win) {scored.p_a_wins:.3f}"
    )


def main() -> None:
    """Parse argv, resolve the bow and its counterfactual, and print the verdict."""
    parser = argparse.ArgumentParser(
        description="How much of the Sisters' edge is the Bow of Avelorn itself?"
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

    print(
        f"{args.models} Sisters of Avelorn shoot, then receive a charge from "
        f'{args.models} White Lions of Chrace ({args.distance}")\n'
    )

    # The printed Sisters, and a counterfactual copy carrying an ordinary bow.
    ordinary = rearm(sisters, "Bow of Avelorn", "Warbow")
    bow_open, bow_felled, bow_react, bow_melee, bow_scored = resolve(
        game, sisters, lions, args.models, args.distance
    )
    warbow_open, warbow_felled, warbow_react, warbow_melee, warbow_scored = resolve(
        game, ordinary, lions, args.models, args.distance
    )

    _report(
        "Bow of Avelorn (as printed)",
        bow_open,
        bow_felled,
        bow_react,
        bow_melee,
        bow_scored,
        args.models,
    )
    print()
    _report(
        "an ordinary Warbow",
        warbow_open,
        warbow_felled,
        warbow_react,
        warbow_melee,
        warbow_scored,
        args.models,
    )

    print(
        "\n  verdict: the Bow of Avelorn is worth its name — and it is the two volleys\n"
        "  together that tell. Its Magical Attacks turn off Lion Cloak (the Lions save\n"
        "  on 6+, not 5+) and its printed Armour Bane stacks with Arrows of Isha, so it\n"
        f"  fells {bow_felled} Lions in the opening volley to the Warbow's {warbow_felled}. "
        f"That one extra body,\n"
        "  compounded by a deadlier Stand & Shoot, breaks the charge's front rank far\n"
        f"  more often — so the Sisters win {bow_scored.p_b_wins:.3f} of the time with the "
        f"bow, {warbow_scored.p_b_wins:.3f}\n"
        "  without, from a melee the full-strength Lions would mostly have won."
    )


if __name__ == "__main__":
    main()
