"""Why a White Lion's cloak is no help against the Sisters of Avelorn.

White Lions of Chrace charge Sisters of Avelorn. The Sisters loose one volley
of the Bow of Avelorn as a Stand & Shoot reaction as the Lions close, then the
two lines meet in close combat.

The lesson is Lion Cloak. A White Lion's cloak improves its armour value by one
against *shooting* attacks — the 5+ save of its Heavy Armour bettered to 4+ —
but only against *non-magical* shots. The Bow of Avelorn has Magical Attacks,
so the cloak is honoured as a no-op and the Lions save on 5+, not 4+. The rule
reads the incoming attack, and a magical arrow turns its protection off.

The second lesson is the striking order. The Sisters have Strike First (their
Initiative is set to 10); the Lions swing the Chracian Great Blade, which has
Strike Last (Initiative set to 1) — so even charging, and even with Elven
Reflexes and the charge bonus lifting them back to I5, the Lions strike after
the Sisters. Charged, the Sisters still land their blows first.

Resolved exactly, no dice rolled. Prints the Stand & Shoot volley, the cloak
comparison (magical vs ordinary shot), the striking order, each side's casualty
distribution, and the combat result — then the verdict.

Usage: uv run python scripts/lion_cloak_demo.py [models] [charge_inches]

Pass -v/--verbose to also emit the DEBUG math trace to stderr.
"""

import argparse
import logging

from avelorn.core.dice import expected_value
from avelorn.core.logging import configure_logging
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.engine.armour import defender_armour
from avelorn.tow.engine.charts import armour_save_target
from avelorn.tow.engine.rules import AttackFacts, GateContext, effective_armour_value
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot
from avelorn.tow.schema.rule import AttackKind


def _lion_save(lions, magical: bool) -> int | None:
    """The armour save a White Lion rolls against a shooting attack.

    Folds the Lions' rules (Lion Cloak among them) over their Heavy Armour under
    an incoming shooting attack, ``magical`` or not, and reads the save target
    off the resulting armour value. Lion Cloak betters it by one only when the
    shot is non-magical.

    Returns:
        The save target (a die face), or None if unarmoured.
    """
    armour_value = defender_armour(lions.loadout.armour)
    if armour_value is None:
        return None
    incoming = GateContext(target_of=AttackFacts(kind=AttackKind.SHOOTING, magical=magical))
    folded = effective_armour_value(
        armour_value,
        lions.loadout.rules,
        incoming,
        wielding=lions.in_hand().name,
        worn=[piece.name for piece in lions.loadout.armour],
    )
    return armour_save_target(folded.value)


def _print_casualties(label: str, casualties: list[float], models: int) -> None:
    print(f"  {label} casualties:")
    print(f"    expected: {expected_value(casualties):.2f} of {models}")
    print("    killed  probability")
    for killed, p in enumerate(casualties):
        bar = "#" * round(p * 40)
        print(f"    {killed:>6}  {p:>10.3f}  {bar}")


def main() -> None:
    """Parse argv, resolve one Lions-into-Sisters charge, and print the verdict."""
    parser = argparse.ArgumentParser(
        description="Why Lion Cloak is no help against the Sisters of Avelorn's magical arrows."
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
    white_lions = game.units["white-lions-of-chrace"]
    sisters = game.units["sisters-of-avelorn"]

    # The Lions charge with their great blade; the Sisters hold their hand
    # weapon for the melee to come, and Stand & Shoot with their sole missile
    # weapon (the Bow of Avelorn) as the reaction.
    lions = game.field(white_lions, args.models).wielding("Chracian Great Blade")
    defenders = game.field(sisters, args.models).wielding("Hand Weapon")
    engagement = game.movement.charge(
        lions, defenders, Charge(args.charge_inches, ChargeArc.FRONT)
    )
    volley = engagement.react(StandAndShoot())
    melee = game.combat.fight(engagement)
    scored = game.combat.result(melee)

    print(
        f"{args.models} White Lions of Chrace charge {args.models} Sisters of Avelorn "
        f'({args.charge_inches}")\n'
    )

    # The Stand & Shoot: the Sisters loose the Bow of Avelorn as the Lions close.
    print("  Stand & Shoot — the Sisters loose the Bow of Avelorn (Magical Attacks):")
    if volley is None:
        print("    (no volley)")
    else:
        print(
            f"    the Lions save on {volley.save_target}+ and lose "
            f"{expected_value(volley.casualties):.2f} of {args.models} before contact"
        )

    # The cloak comparison: the same Lions, the same Heavy Armour, shot at by a
    # magical arrow and by an ordinary one. Lion Cloak betters the save only
    # against the ordinary shot.
    magical = _lion_save(lions, magical=True)
    ordinary = _lion_save(lions, magical=False)
    print(
        "\n  Lion Cloak against the incoming shot:\n"
        f"  - magical arrows (Bow of Avelorn): {magical}+  (cloak honoured, no help)\n"
        f"  - an ordinary shot:                {ordinary}+  (cloak betters the save by one)\n"
        "\n  verdict: Lion Cloak reads the attack, not the armour. The Bow of Avelorn's\n"
        "  Magical Attacks turn the cloak off — the Lions weather the volley on the\n"
        "  bare 5+ of their Heavy Armour."
    )

    # The striking order: the Sisters strike first (Strike First sets I to 10),
    # the Lions after (the great blade's Strike Last sets I to 1, lifted by Elven
    # Reflexes and the charge bonus but not past the Sisters).
    standing = engagement.b
    first = melee.first_striker
    a_init, b_init = melee.a_initiative.value, melee.b_initiative.value
    if first is standing:
        order = f"the Sisters strike first (I{b_init} vs I{a_init}) — charged, but faster"
    elif first is None:
        order = f"simultaneous (I{a_init} each)"
    else:
        order = f"the Lions strike first (I{a_init} vs I{b_init})"
    print(f"\n  striking order: {order}\n")

    _print_casualties("Lions (A)", melee.a_casualties, args.models)
    print()
    _print_casualties("Sisters (B)", melee.b_casualties, args.models)

    print(
        f"\n  combat result:\n"
        f"  - P(Lions win):   {scored.p_a_wins:.3f}\n"
        f"  - P(draw):        {scored.p_draw:.3f}\n"
        f"  - P(Sisters win): {scored.p_b_wins:.3f}"
    )

    if melee.notes:
        print("\n  not factored into the melee math (no seam consumes them yet):")
        for note in melee.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
