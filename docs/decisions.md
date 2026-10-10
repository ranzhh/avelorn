# Design notes

Open questions, parked. A note leaves when it becomes a change or an issue.

## The armour save's bounds

**Paused 2026-08-20**, while moving printed bounds onto the amount they bound.
The bound on characteristics was fixed; this one was left alone.

One bug, verified, and one question:

- **No global cap in game.** `defender_armour` (`tow/fielding.py:398`) floors
  at `BEST_ARMOUR_VALUE = 2`, but the save step (`tow/steps.py:749`) floors
  the improved value only at the printed maxima of the amounts added.
  `add: {armour-value: 1}` with no bound is legal, and returns 1+ on a 2+
  model. Latent: Parry and Lion Cloak both print a bound.
- **Which bound wins.** The save step clamps the finished sum by every bound,
  so two rules improving a 4+ under different caps give 3+ whichever comes
  first, as `dd9cc51` did for characteristics.

That takes the most restrictive bound, and the open question is whether it
should: **does a printed cap bound the final value, or its own rule's
contribution?** Clamping the sum by every bound gives 3+ above; reading each
cap as local gives 2+.

Settle the printed rule first — it likely decides whether the cap belongs to
the model or to the save. Unverified, from memory: 2+ at list building, 3+ for
something mounted on a monster (per an FAQ, unpinned), and an in-game effect
prints its own bound but stays subject to the build cap. The repo is no better
sourced — `BEST_ARMOUR_VALUE` has no citation and no per-troop-type cap exists.
