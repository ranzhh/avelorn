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

## The swing view

**Paused 2026-08-27**, after a specimen. `Matchups.svelte` and `matchups.ts`
land as they are; the cell semantics they carry are wrong, and the replacement
is not designed yet. Reproduce every number below with
`uv run python scripts/swing_demo.py`.

The grid as built reports P(row wins the round) under one stance. That is not a
verdict, it is an artefact of the stance chosen. Shock cavalry resolved
stationary reads as a rout: 5 Dragon Princes against 20 Swordmasters win 9.4% of
rounds stationary and 47.2% charging the rear. A cell showing either number
alone misleads.

The direction instead: one pairing at a time, every condition ranked by how far
it moves the round. A condition is one field of the `POST /fight` body, which
makes the axis list complete by construction rather than by judgement.

Four things the specimen settled.

**The charge is not the top condition.** Swordmaster frontage spans 49.4pp,
Dragon Prince size 41.8pp, the charge and its arc 40.8pp. Frontage is free and
outranks a charge.

**Every condition that costs points moves the round 0.0pp.** Standard bearers,
the Drakemaster, the Bladelord and Drilled span 46 points between them and
change nothing. Four of the five are dropped without a note: buying a Standard
Bearer takes the muster from 185 to 192 pts and the round reports the same 24
held rules it reported without one. Only Drilled says `special rule not
factored`. `combat result component not factored: standards (#28)` is reported
at round level whether a standard is bought or not. A tool for building lists
cannot rank the buyable dimension until #28 lands.

**The Break multiplier is a constant of the datasheet.** `break_test`
(`phases/combat.py:1829`) reads the *natural* 2D6 for Break and the modified
roll only for the Fall Back or Give Ground split. So P(breaks | loses) held at
0.1667 for the Dragon Princes and 0.2778 for the Swordmasters across every state
resolved -- 6/36 and 10/36, P(2D6 over Ld 9 and Ld 8). The combat result margin
never reaches it. Conditions therefore fall into two classes that cannot share a
ranking: those moving P(win the round), and those moving the loser's effective
Leadership (Terror) or forcing the outcome (Stubborn zeroes Breaks). A single
swing number conflates them.

**One condition at a time mis-ranks.** The ranking calls DP weapon a 13.2pp
swing, its value at the reference. The Lance is worth 6.0pp receiving a rear
charge and 31.2pp making one. Full crossing is exponential, so the answer is
probably pin-and-re-rank rather than a factorial.

Four open questions.

1. **The specimen was hard to read.** Eleven range bars, a seven-segment
   diverging stack and an interaction table did not carry the findings; the
   findings had to be written underneath in prose. The layout needs another
   attempt before any of it is built.
2. **The reference is still a choice.** Ranges soften it, but the tick on each
   track comes from a state someone picked. Baseline-free framings exist and
   none has been tried.
3. **`not_modelled` is round-level, so "why is this zero" is unanswerable per
   condition.** All eleven axes return the same 24 notes. Attributing a held
   rule to the condition it would have moved is engine work.
4. **One round overstates the charge.** `/fight` covers no pursuit and no second
   round, where a charger has no bonus. Every swing figure involving a charge is
   optimistic by an unmeasured amount.
