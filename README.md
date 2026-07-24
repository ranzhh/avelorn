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

The core tenet is that the engine models **distributions, not averages** — and the questions worth asking only pay off when you fold those distributions into each other. Here is one. You are the High Elf player. A unit of **White Lions of Chrace** is 10" from your **Sisters of Avelorn** and will charge next turn whatever you do; this turn you can loose the Sisters' volley at those Lions, or at some other target. Either way the Lions charge, the Sisters Stand & Shoot as they come, and the lines fight. So: **does shooting the Lions first raise your chance of winning that combat, and by how much?**

The opening volley does not fell "about three" Lions — it fells a *spread* (most often two to four, sometimes none, sometimes six). Each outcome leads to a different charge and a different combat. The answer is every branch resolved exactly and mixed by how likely it is — a fold, `Σ_k P(volley fells k) · P(win | 10−k charge)` — not the average plugged in once. Walk it through the context-manager surface (`scripts/bow_of_avelorn_demo.py`):

```python
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot

game = TOWGame.load_data()
sisters = game.units["sisters-of-avelorn"]
lions = game.units["white-lions-of-chrace"]

def win_given_charge(sheet, charging):
    """P(Sisters win) when `charging` Lions charge — Stand & Shoot, then melee."""
    if charging == 0:
        return 1.0
    lions_unit = game.field(lions, charging).wielding("Chracian Great Blade")
    defenders = game.field(sheet, 10).wielding("Hand Weapon")
    turn = game.turn()
    with turn.movement() as movement:
        engagement = movement.charge(lions_unit, defenders, Charge(10, ChargeArc.FRONT))
        engagement.react(StandAndShoot())   # thins the chargers AND scores — folded natively
    with turn.combat() as combat:
        return combat.result(combat.fight(engagement)).p_b_wins

def win_if_shot(sheet):
    """Fold the opening volley's whole casualty distribution into P(Sisters win)."""
    with game.turn().shooting() as shooting:
        opening = shooting.volley(game.field(sheet, 10), game.field(lions, 10), distance=10)
    return sum(p * win_given_charge(sheet, 10 - k)         # mix over every outcome...
               for k, p in enumerate(opening.casualties))  # ...weighted by its probability
```

The counterfactual is a one-line datasheet edit — swap the printed bow, re-field, and every downstream probability re-resolves from the new gear:

```python
def rearm(unit, frm, to):
    return unit.model_copy(update={"equipment": [to if e == frm else e for e in unit.equipment]})

warbow = rearm(sisters, "Bow of Avelorn", "Warbow")
for sheet in (sisters, warbow):
    print(win_given_charge(sheet, 10),  # shoot elsewhere: Lions charge at full strength
          win_if_shot(sheet))           # shoot the Lions first: the volley folded in
```

Run as-is it prints:

```
  with the Bow of Avelorn:
    opening volley fells (of 10):  0:2%  1:12%  2:24%  3:28%  4:21%  5:10%  6:3%
    shoot elsewhere — Lions charge at full strength:  P(Sisters win) 0.298
    shoot the Lions first (volley folded in):         P(Sisters win) 0.731   (+0.434)

  with the ordinary Warbow:
    opening volley fells (of 10):  0:6%  1:20%  2:30%  3:25%  4:14%  5:5%  6:1%
    shoot elsewhere — Lions charge at full strength:  P(Sisters win) 0.252
    shoot the Lions first (volley folded in):         P(Sisters win) 0.640   (+0.389)
```

So shooting the Lions first is decisive: with the Bow of Avelorn it turns a combat the Sisters mostly lose (0.298) into one they mostly win (0.731). That number is the whole spread of volley outcomes folded in — the 2% chance of felling none and the 3% chance of felling six both weighed, not a rounded mean standing in for them.

And the bow is worth its name. It leads the ordinary Warbow at both ends — 0.731 vs 0.640 when you shoot first — because of two printed things the Warbow lacks: **Magical Attacks**, which turn off a White Lion's **Lion Cloak** (so the Lions save on 6+, not 5+), and a printed **Armour Bane (1)** that stacks with the one the Sisters' **Arrows of Isha** already grants any bow. You can see it in the felled-Lions distribution above: the bow's mass sits a full model to the right.

One thing the engine does *not* yet do, and the fold shows exactly where: the Stand & Shoot chains into the melee for free — `fight` enters the charger already thinned by the reaction and scores its wounds toward the Sisters' combat result — but that is the *same* combat. The opening volley is a *previous turn*, whose wounds must not score this combat, so it is folded here as the mixture above rather than handed to `fight` as prior losses. The missing primitive is a way to enter a combat thinned-but-unscored (a cross-turn battle layer); until then, the mixture is the honest fold, and it is exact.

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
