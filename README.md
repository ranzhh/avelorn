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

## Demo: how much is the Bow of Avelorn worth?

`scripts/bow_of_avelorn_demo.py` puts two of the trickier High Elf units on the table and asks a question the game actually turns on. **White Lions of Chrace** charge **Sisters of Avelorn**; the Sisters loose one volley of the Bow of Avelorn as a Stand & Shoot reaction as the Lions close, then the lines meet. You walk the turn as the rulebook plays it — the charge and its reaction in the Movement phase, the melee in the Combat phase:

```python
from avelorn.core.dice import expected_value
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot

game = TOWGame.load_data()          # the data/ tree, the single source of truth
sisters = game.units["sisters-of-avelorn"]
lions = game.units["white-lions-of-chrace"]

def resolve(sisters_sheet):
    # 10 Lions charge 10 Sisters 8"; the Sisters hold their hand weapon for
    # the melee and Stand & Shoot with their bow as the reaction.
    lions_unit = game.field(lions, 10).wielding("Chracian Great Blade")
    defenders = game.field(sisters_sheet, 10).wielding("Hand Weapon")
    turn = game.turn()
    with turn.movement() as movement:
        engagement = movement.charge(lions_unit, defenders, Charge(8, ChargeArc.FRONT))
        volley = engagement.react(StandAndShoot())
    with turn.combat() as combat:
        result = combat.result(combat.fight(engagement))
    return volley, result

volley, result = resolve(sisters)
print(f"Stand & Shoot: Lions save on {volley.save_target}+, "
      f"{expected_value(volley.casualties):.2f} of 10 fall before contact")
print(f"P(Sisters win the melee): {result.p_b_wins:.3f}")
```

Then the arbitrary question — *how much of that is the Bow of Avelorn itself?* Because the datasheet is the source of truth, the counterfactual is a one-line edit: trade the printed bow for an ordinary Warbow, re-field, and re-ask.

```python
def rearm(unit, frm, to):
    equipment = [to if item == frm else item for item in unit.equipment]
    return unit.model_copy(update={"equipment": equipment})

warbow_volley, warbow_result = resolve(rearm(sisters, "Bow of Avelorn", "Warbow"))
print(f"with an ordinary Warbow: Lions save on {warbow_volley.save_target}+, "
      f"Sisters win {warbow_result.p_b_wins:.3f}")
```

Run as-is it prints the two runs side by side:

```
  Bow of Avelorn (as printed):
    Stand & Shoot: Lions save on 6+, 1.48 of 10 fall before contact
    melee: P(Sisters win) 0.298   P(draw) 0.158   P(Lions win) 0.544

  an ordinary Warbow:
    Stand & Shoot: Lions save on 5+, 1.20 of 10 fall before contact
    melee: P(Sisters win) 0.252   P(draw) 0.153   P(Lions win) 0.595
```

The gap decomposes into two printed things the ordinary bow lacks. The Bow of Avelorn has **Magical Attacks**, so a White Lion's **Lion Cloak** — which betters its save by one against *non-magical* shooting — is turned off, and the Lions weather the volley on 6+ instead of 5+. And its printed **Armour Bane (1)** stacks with the one the Sisters' **Arrows of Isha** already grants any bow, so a natural 6 To Wound improves Armour Piercing by two. Worth about a quarter of a charger extra per volley, and it carries into the melee.

Run it via `make demo DEMO=bow_of_avelorn`, or drive it directly:

```sh
uv run python scripts/bow_of_avelorn_demo.py 10 8   # 10 models a side, an 8" charge
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
