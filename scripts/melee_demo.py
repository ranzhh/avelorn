"""Did you know charging can be the worse option?

Two equal blocks of Elven Spearmen; one charges, the other stands and receives.
The charger strikes first, but its rank rules lapse on the charge (Press of
Battle, Fight in Extra Rank) -- so it swings with one rank while the unit it hits
swings with three. Receiving wins the combat more often than delivering it.
"""

from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame


def main() -> None:
    """Resolve one spearmen-on-spearmen charge and print who is favoured."""
    game = TOWGame.load_data()
    spearmen = game.units["elven-spearmen"]

    chargers = game.field(spearmen, 20).wielding("Thrusting Spear")
    receivers = game.field(spearmen, 20).wielding("Thrusting Spear")
    engagement = game.movement.charge(chargers, receivers, Charge(8, ChargeArc.FRONT))
    engagement.react()  # Hold — Spearmen carry no missile weapon to Stand & Shoot with
    scored = game.combat.result(game.combat.fight(engagement))

    total = scored.p_a_wins + scored.p_draw + scored.p_b_wins
    print('20 Elven Spearmen charge 20 Elven Spearmen (8"):')
    print(f"  P(charger wins)   {scored.p_a_wins:.3f}")
    print(f"  P(draw)           {scored.p_draw:.3f}")
    print(f"  P(receiver wins)  {scored.p_b_wins:.3f}   <- the charger's ranks lapse")
    # Resolved in exact rationals, so this is 1 and not 0.9999999999999999. The
    # fractions themselves run to fifteen digits, which is why the rounded
    # figures above are the readable form.
    print(f"  the three sum to  {total} exactly")


if __name__ == "__main__":
    main()
