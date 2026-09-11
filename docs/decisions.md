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

## Attribution needs a chosen quantity

**Paused 2026-08-27**, during review of #203. The To Hit ledger lands as it
stands. What it should become is below. Reproduce every number with
`uv run python scripts/attribution_demo.py`.

### The bug that opened it

Two volleys against 20 Dwarf Warriors at 6in, as the resolved dock prints them:

    Sisters of Avelorn   AV 5  AP 0  ->  6+
    Elven Archers        AV 5  AP 0  ->  5+

Identical operands, different answer, nothing on screen accounting for the gap.
`Arrows of Isha` moves the armour save through a compiled modifier. The
`armour_piercing` the report carries is `profile.armour_piercing`, the weapon's
*printed* AP, which is 0 on the Bow of Avelorn. #203 asserted that the wound and
save targets are single chart lookups and so need no ledger. That is false for
the save.

### Why a target cannot be the explanation

The Sisters volley carries three modifiers on the armour save:

    make-armour-saves  +1  trigger=None                source='Arrows of Isha'
    make-armour-saves  +1  trigger=natural 6 to wound  source='Armour Bane (1)'
    make-armour-saves  +1  trigger=natural 6 to wound  source='Armour Bane (1)'

So the save is not 6+. It is 6+ where the wound was a natural 5, and no save at
all where it was a natural 6 -- two Armour Bane records take the target to 8+,
off the die. A reported target is a projection of a branching walk onto one
integer, and it is lossy exactly when a modifier is conditional.

Keep the target anyway. "I need a 6+" is how the game is played at the table.
Demote it from explanation to printed summary, and attribute elsewhere.

### The measure that survives both

Contribution to a reported number, computed by resolving the walk with and
without each record. It treats conditional and unconditional modifiers alike,
and it reaches what no ledger of targets can: a `Reroll` and a `Transform` move
no target, so Ithilmar Weapons and Killing Blow are structurally invisible to a
target ledger. The Sisters volley happens to carry no re-roll grant, so that
part is argued rather than shown.

The case for the conditional row is not a judgement call:

    neither             5/27   = 0.18519      save 5+ throughout
    Arrows of Isha only 25/108 = 0.23148      alone  +0.04630
    Armour Bane only    25/108 = 0.23148      alone  +0.04630
    both                55/216 = 0.25463      joint  +0.06944

The modifier that appears nowhere on the panel is worth exactly what the one
that does is worth.

### Leave-one-out is the wrong estimator

The two are substitutes -- both push the save off the die, and there is only so
much save to remove:

    leave-one-out  +0.02315 each   understates by half
    alone          +0.04630 each   the sum overshoots the joint by +0.02315
    Shapley        +0.03472 each   sums to +0.06944, the joint exactly

Only Shapley makes the rows sum to the whole. It costs 2^N walks. N is the count
of distinct sources plus re-roll grants, and across all 13 shooting pairings the
corpus can build it never exceeds 3, so 2^N never exceeds 8. A walk is about a
millisecond. Melee is unmeasured; `phases/combat.py` will carry more per round
and 2^N may not survive there.

### The conditional row's shape is the easy half

`Modifier.trigger` is `NaturalRoll | None` and `NaturalRoll` is exactly
`(roll: Stage, face: int)`. That is the whole conditional vocabulary in the
schema. So the row is a groupby over a closed key -- one row per `(stage, face)`,
carrying the resulting target on that branch and the contribution:

    on a natural 6 To Wound   no save   Armour Bane (1) x2   +0.03472

### Attribution needs a chosen quantity

A contribution is meaningless without saying to *what*. Same two rules, same
volley, four reported numbers, three target sizes:

    quantity                  x8         x16         x20
    p_unsaved           +0.03472    +0.03472    +0.03472
    felled              +0.27778    +0.27778    +0.27778
    forced to test      +0.08080    +0.01105    +0.00194
    flees or wiped      +0.00639    +0.00000    +0.00000

Against 16 Dwarf Warriors both rules contribute exactly zero to whether the
target runs, while contributing the same +0.03472 to the per-shot unsaved chance
they always do. At 20 there is no share to compute at all -- the total is zero.
The mechanism is the threshold in `make_panic_tests`: a unit tests only on losing
more than a quarter of its models (`killed * 4 > size`). Twenty dwarves need 6
gone and the volley averages 2, so nothing the bow does reaches the gate.

"Did this rule matter" therefore has no answer. It has an answer per quantity,
and the answers include "enormously" and "not at all" for one rule in one
volley. The panel needs a selector for which number is under inspection, and
the attribution machinery runs against whichever projection is chosen.

The projections are a bounded list of pure functions of the report already
returned: per-shot unsaved chance, expected casualties, the casualty
distribution, P(target runs), P(win the round), P(enemy breaks), points traded.

Two display rules fall out, and the current panel would get both wrong.

- **A zero must read as "does not reach this number", not as 0%.** A blank or a
  `0.00` reads as "checked, negligible" when the truth is "this quantity is
  gated and the rule never gets there".
- **Where the quantity is zero throughout there is no attribution.** Not 50/50,
  not 0/0. The panel has to say so.

### Open

1. **The projection list is not settled.** Seven candidates above, no argument
   yet for which belong and which are noise.
2. **Reordering is predicted and unshown.** Because panic is gated, a rule that
   *widens* the casualty distribution should beat one that lifts its mean by the
   same amount, for "flees" alone. Needs a unit with Multiple Wounds or Killing
   Blow. Untested.
3. **Melee N is unmeasured**, so the exact-Shapley budget is unproven outside
   shooting. A stated fallback is needed for large N, cited on screen when used.
4. **Whether contribution belongs in the engine or the caller.** Ablation means
   re-resolving, which the API has no route for today. A caller can do it with
   N+1 requests. The engine could do it in one.
