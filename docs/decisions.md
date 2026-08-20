# Design notes

Open questions, parked. A note leaves when it becomes a change or an issue.

## The armour fold's bounds

**Paused 2026-08-20**, while moving printed bounds onto the amount they bound.
The characteristic seam was fixed; this one was left alone.

Two bugs, both verified:

- **No global cap in game.** `defender_armour` (`engine/armour.py:25`) floors
  at `BEST_ARMOUR_VALUE = 2`, but `effective_armour_value`
  (`engine/rules.py:848`) floors only at each effect's own printed `maximum`.
  `add: {armour-value: 1}` with no bound is legal, and returns 1+ on a 2+
  model. Latent: Parry and Lion Cloak both print a bound.
- **Order dependence.** It clamps per operation, so two rules improving a 4+
  under different caps give 3+ as `X(+1, max 2+), Y(+1, max 3+)` and 2+
  reversed.

`dd9cc51` fixed the same order bug on characteristics by clamping the finished
sum. Why that doesn't just transfer is the open question: **does a printed cap
bound the final value, or its own rule's contribution?** Clamping the sum by
every bound takes the most restrictive (3+ above); reading each cap as local
gives 2+.

Settle the printed rule first — it likely decides whether the cap belongs to
the model or to the fold. Unverified, from memory: 2+ at list building, 3+ for
something mounted on a monster (per an FAQ, unpinned), and an in-game effect
prints its own bound but stays subject to the build cap. The repo is no better
sourced — `BEST_ARMOUR_VALUE` has no citation and no per-troop-type cap exists.
