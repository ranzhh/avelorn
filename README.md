# Avelorn

A toolkit for tabletop wargames, starting with **Warhammer: The Old World**.

It comes down to three things, all built on one curated dataset. The first is a unit and army database you can query. The second is an army-list planner that knows the rules well enough to catch an illegal list. The third is a battler that works out combat odds, and rather than rolling dice thousands of times and averaging the results, it computes the exact distribution. That lets it answer the questions a game actually hinges on, like the odds a unit breaks and runs, instead of just handing back a mean.

The data is hand-authored YAML under `data/`, and that is the single source of truth. Special rules are data too, so they compile into the dice walk instead of living as hard-coded special cases.

## What's built so far

The dice engine is the part that works today.

- **Schema** (`tow/schema`) models units, weapons, armour, and rules as Pydantic types, validated as they load from YAML; `TOWRepository` (`tow/data`) is the one place that knows the `data/` tree's layout and hands back the loaded registries.
- **The game** (`tow/game`, `tow/turn`) is the corpus in play. `TOWGame.load_data()` assembles it from the data tree; a `Contingent` (`tow/contingent`) is a unit as fielded — a chosen model count, a resolved loadout, and the weapon it takes in hand. You walk a turn phase by phase (`with turn.movement() as movement:`), each phase a small surface over the maths.
- **The maths engine** (`tow/engine`) resolves an attack exactly — from to-hit through to-wound to the armour and ward saves — and returns a casualty distribution built on the hit/wound/save charts. Special-rule effects fold into the dice walk straight from the data; the situational modifiers are gated on a typed picture of the action (did the unit move? how far to the target? is the incoming shot magical?).
- **The phases** (`tow/phases`) are its callers. **Shooting** resolves a volley end to end. **Combat** resolves a full round: both sides strike in Initiative order, casualties tally into a combat result, and the loser takes its break test. **Movement** carries the **charge sequence** — a unit charges, the target reacts with Stand & Shoot, and the survivors fight — all as exact distributions.
- **Panic tests** take a casualty distribution and return the exact chance the target is forced to test, then holds, falls back, flees, or is wiped out.
- **Querying** (`tow/query`) lets you ask for a specific outcome, such as `at least`, `at most`, `exactly`, or `between` over a named variable, and hands back its probability.
- **Army-list entries**: a `Complement` (`tow/muster`) sizes and equips a datasheet — a chosen model count and options, validated against what the unit is allowed to take — and derives its points and effective loadout. It is the first piece of the list planner.
- **Importer** pulls units off tow.whfb.app into the `data/` tree (see credits).

The rest is still to come, roughly in the order it matters.

- **More army data.** A handful of High Elf units exist today, which is enough to exercise the engine but nowhere near a playable database. Filling this out is what the importer is for.
- **A backing store.** Everything loads from YAML on each run right now. The plan is to load that YAML into SQLite once and query it from there, so the database can grow past what you would want to parse from files every time.
- **The query API.** This is an HTTP (and MCP) surface over that store, so the unit and army database becomes reachable from something other than a Python import. It is the queryable half of the goal.
- **The list planner.** You build an army list and have it checked against the rules: points limits, army composition, and unit availability. The per-unit half exists as `Complement`; what is missing is the composition above it.
- **The magic phase.** The exact dice walk underneath is generic — shooting and close combat are its first two callers — so what is missing is the phase resolver rather than the maths.

## The kind of thing you can ask it

Here is the sort of question the engine is built to answer exactly. Take two of the trickier High Elf units — **Sisters of Avelorn** and **White Lions of Chrace** — and play out a fight: the Lions stand 10" off, the Sisters loose a full volley in their own turn, then next turn the Lions charge that gap, the Sisters get a Stand & Shoot reaction, and the lines meet in melee. Then ask the question that actually decides how you'd build the list: *how much of the Sisters' edge is the Bow of Avelorn itself, rather than the elf holding it?* Swap the bow for an ordinary one and the engine re-answers everything — exactly, no dice rolled.

You walk it as the rulebook plays it, phase by phase, through the context-manager surface (`scripts/bow_of_avelorn_demo.py`):

```python
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot

game = TOWGame.load_data()
sisters = game.units["sisters-of-avelorn"]
lions = game.units["white-lions-of-chrace"]

def resolve(sisters_sheet, distance=10):
    lions_unit = game.field(lions, 10)
    defenders = game.field(sisters_sheet, 10)

    # The Sisters' turn: standing still, they loose a full volley at the Lions
    # `distance` off — every rank fires (Volley Fire) and there is no penalty.
    with game.turn().shooting() as shooting:
        opening = shooting.volley(defenders, lions_unit, distance=distance)

    # UGLY SEAM: carry the opening volley's casualties across the turn by hand.
    # The engine has no cross-turn casualty state yet (see the roadmap), so we
    # just remove the expected number of felled Lions before they charge. Crude
    # — it rounds a whole distribution to one integer — but it lets the opening
    # volley and the Stand & Shoot below actually combine, which is the point.
    survivors = lions_unit.remove_casualties(round(opening.expected_casualties))

    # The Lions' turn: the survivors charge; the Sisters Stand & Shoot (front
    # rank only, at a penalty), then the two lines fight. This reaction's felled
    # Lions the engine *does* carry in for free — they don't swing back, and
    # their wounds score for the Sisters.
    lions_turn = game.turn()
    with lions_turn.movement() as movement:
        engagement = movement.charge(
            survivors.wielding("Chracian Great Blade"),
            defenders.wielding("Hand Weapon"),
            Charge(distance, ChargeArc.FRONT),
        )
        reaction = engagement.react(StandAndShoot())
    with lions_turn.combat() as combat:
        melee = combat.fight(engagement)
        result = combat.result(melee)
    return opening, reaction, melee, result
```

The counterfactual is where the data-as-source-of-truth pays off: to ask "what if they had an ordinary bow?" you change one printed name on the datasheet and re-field. Everything downstream — the loadout, the rules that key off it, every probability — re-resolves from the new gear.

```python
def rearm(unit, frm, to):
    equipment = [to if item == frm else item for item in unit.equipment]
    return unit.model_copy(update={"equipment": equipment})

bow = resolve(sisters)                                # the Bow of Avelorn, as printed
warbow = resolve(rearm(sisters, "Bow of Avelorn", "Warbow"))   # an ordinary bow
```

Run as-is it prints the two runs side by side:

```
  Bow of Avelorn (as printed):
    opening volley (their turn):    8 shots, Lions save 6+, 2.96 wounds → 3 felled, 7 charge
    Stand & Shoot (as they charge): 5 shots, Lions save 6+, 1.48 wounds
    melee casualties:  Lions lose 1.93, Sisters lose 2.88
    combat result:     P(Sisters win) 0.730   P(draw) 0.102   P(Lions win) 0.168

  an ordinary Warbow:
    opening volley (their turn):    8 shots, Lions save 5+, 2.41 wounds → 2 felled, 8 charge
    Stand & Shoot (as they charge): 5 shots, Lions save 5+, 1.20 wounds
    melee casualties:  Lions lose 1.94, Sisters lose 3.60
    combat result:     P(Sisters win) 0.616   P(draw) 0.143   P(Lions win) 0.241
```

The gap comes down to two printed things the ordinary bow lacks. The Bow of Avelorn has **Magical Attacks**, so a White Lion's **Lion Cloak** — which betters its save by one against *non-magical* shooting — is turned off, and the Lions weather it on 6+ instead of 5+. And its printed **Armour Bane (1)** stacks with the one the Sisters' **Arrows of Isha** already grants any bow, so a natural 6 To Wound improves Armour Piercing by two. That is a steady *proportional* edge — about a fifth (~23%) more wounds per volley, whatever its size.

The interesting part is how the two volleys **combine**. On its own the bow's edge is small in absolute terms — +0.55 wounds across the eight-shot opening volley, only +0.28 in the five-shot Stand & Shoot (a charge reaction fires the front rank alone). But they stack: the deadlier opening volley fells 3 Lions to the Warbow's 2, and the deadlier Stand & Shoot thins them again, and together they far more often drop the charge below a full front rank of five — so the Lions arrive with fewer blows to throw. That is why the melee tips so hard: with the bow the Sisters win **0.730**, with the Warbow **0.616**, from a charge the full-strength Lions would mostly have won (~0.30). A one-model difference in the opening volley is worth a tenth of the whole combat.

(One honest caveat, flagged in the code: the Stand & Shoot's casualties chain into the melee natively — the engine enters the charger already thinned and scores its wounds — but a *prior turn's* shooting has no home in the engine yet, so the opening volley's kills are carried across the turn by hand, rounding a distribution to a whole number. A continuous battle that tracks casualties across turns is a planned layer on top; this is a stand-in for it.)

Run it via `make demo DEMO=bow_of_avelorn`, or drive it directly:

```sh
uv run python scripts/bow_of_avelorn_demo.py 10 10   # 10 a side, the Lions 10" off
```

Add `-v` for the full DEBUG math trace on stderr.

Other demos exercise the rest of the engine: `shooting_demo.py` (one unit shoots another, with the panic tests), `melee_demo.py` (a round of close combat), `charge_demo.py` (the full charge sequence, Stand & Shoot included), `turn_demo.py` (walking a whole player-turn), and `lion_cloak_demo.py` and `receiving_a_charge_demo.py` (two more worked cautionary tales). Each is `scripts/<name>_demo.py`, runnable as `make demo DEMO=<name>`.

## Getting started

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
git clone <repo> && cd warhammer
make install   # uv sync + install the pre-commit hooks
make test      # run the suite
make demo      # end-to-end shooting demo from the data files
make lint      # ruff + ty + hygiene hooks over the whole tree
```

## Credits

Unit data is imported from **[tow.whfb.app](https://tow.whfb.app)**, an
excellent community reference for The Old World. Thanks to its author,
**@FlammableHero**, for building and maintaining it.
