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

## Conditions are ambient, not arguments

**Paused 2026-08-28**, during review of #203, #204 and #205. Nothing below is
built. The three branches land or are reworked against it.

Each of the three grew a condition surface of its own. `conditions.ts:11` on
#205 holds `moved`, `hit` and `battleStrength`, scoped by its own docstring to
"the facts about a shot". `matchups.ts:13` on #204 holds a `Stance` of
`engaged` or `charged` for a melee, digested into the grid's cache key at
`matchups.ts:47`. The action menu on #201 carries a third variant in its
charge, shoot and engaged choice. No one of the three can read the other two.

The swing note above already settles what a condition is: one field of the
`POST /fight` body. That definition does not stop at the fight route. `POST
/volley` takes fields of the same kind. #205 added `moved` to that route alone.
Both routes should take one shared request component instead.

The shape: one set of conditions held for the table, phase-agnostic, read by
every calculation rather than passed to one. Setting a condition re-asks every
open question at once. A number on screen is always a number under the current
conditions.

### What it settles

**The swing view gets its axis for free.** The note above wants every condition
ranked by how far it moves the round, with the axis list complete by
construction. A shared component *is* that list. It also removes the reason the
grid misleads. 5 Dragon Princes against 20 Swordmasters win 9.4% of rounds
stationary and 47.2% charging the rear, so a cell carrying one number is
carrying an artefact of a stance chosen elsewhere. Under ambient conditions the
stance is not chosen elsewhere.

**A condition is an ablatable record.** The attribution note above moves
explanation off the target and onto each record's contribution, resolved by
Shapley over the compiled records. A condition is a record of that kind. Ask
the volley with `moved` and without it, and the difference is that condition's
contribution, computed by the same machinery that prices `Arrows of Isha`.
This is what makes #205's deliberately unnamed stepper tractable: a situational
-1 needs no rulebook name to be worth a measured amount.

It also bears on the fourth open question above, whether contribution belongs
in the engine or the caller. Conditions held against a table make ablation a
re-resolve with one record dropped. Conditions riding in the request make it
N+1 calls from the caller. That question and the one below are the same
question.

**One vocabulary across two phases.** Elven Archers at 6in hit on 3+ standing
and 4+ having marched, for expected casualties of 1.33 against 0.62. A charge
is worth up to +3 Initiative into the front. Both are the same kind of fact
about the same turn. Only the first is currently expressible.

### Open

Whether the conditions ride in the request or are held server-side against a
table identity. Sending them keeps the API stateless and costs a wider body on
every call. Holding them needs a table resource. Nothing here has one yet.

Whether a condition that no corpus entry backs should be offered at all.
Importing cover and large target would turn #205's unnamed stepper into named
toggles. Until then the stepper asserts a value nothing can check.
