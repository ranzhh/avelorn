# Avelorn

A toolkit for tabletop wargames, starting with **Warhammer: The Old World**.

It comes down to three things, all built on one curated dataset:
- a unit and army database you can query.
- an army-list planner that knows the rules well enough to catch an illegal list.
- a battler that works out combat odds, and rather than rolling dice thousands of times and averaging the results, it computes the exact distribution. That lets it answer the questions a game actually hinges on, like the odds a unit breaks and runs, instead of just handing back a mean.

The (unit, weapon...) data is YAML under `data/`, as the single source of truth. Special rules are data too, so they compile into the dice walk instead of living as hard-coded special cases. This is potentially subject to change, in case I encounter a harder rule which would force a structure too ugly / hard to parse.

## What is this vibe coded bullshit?
I am a big fan of writing clean and concise code. LLMs have proven to help me massively at work, but they definitely don't produce the best code on the first try without steering; maybe that will change in the future.

This project is an attempt to write code for what I know to be a very hard endeavour - mapping a game with hooks and rules that interact with each other - using only LLMs. As of now, the only piece of the codebase I have touched by hand is this README, and even then just the parts until now.

I believe that in order for me to get better at using LLMs, a project such as this - forcing me to wrestle with their inherent weaknesses - will massively help. I hope to become better at planning before prompting and properly steering these models.

The tooling used so far is Claude Code + Claude Opus 4.8 and Claude Fable 5. If you're going to dive into this project, thanks for sticking it out so far! The fun part begins now.


## What's built so far

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

The core tenet is that the engine models **distributions, not averages** — and the questions worth asking only pay off when you fold those distributions into each other. Here is one, and the answer turns on *which unit is asking*. A unit of **White Lions of Chrace** is 10" away and will charge next turn whatever you do; this turn your unit can loose its volley at those Lions, or at some other target. Either way the Lions charge, your unit Stand & Shoots as they come, and the lines fight. So: **does shooting the Lions first raise your chance of winning that combat, and by how much?** Ask it of two different units — elite **Sisters of Avelorn** and rank-and-file **Elven Archers** — and the same tactic gives opposite advice.

The opening volley does not fell "about three" Lions — it fells a *spread*. Each outcome leads to a different charge and a different combat. The answer is every branch resolved exactly and mixed by how likely it is — a fold, `Σ_k P(volley fells k) · P(win | 10−k charge)` — not the average plugged in once. Walk it through the context-manager surface (`scripts/bow_of_avelorn_demo.py`):

```python
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot

game = TOWGame.load_data()
lions = game.units["white-lions-of-chrace"]

def win_given_charge(defender, charging):
    """P(defender wins) when `charging` Lions charge it — Stand & Shoot, then melee."""
    if charging == 0:
        return 1.0
    lions_unit = game.field(lions, charging).wielding("Chracian Great Blade")
    unit = game.field(defender, 10).wielding("Hand Weapon")
    turn = game.turn()
    with turn.movement() as movement:
        engagement = movement.charge(lions_unit, unit, Charge(10, ChargeArc.FRONT))
        engagement.react(StandAndShoot())   # thins the chargers AND scores — folded natively
    with turn.combat() as combat:
        return combat.result(combat.fight(engagement)).p_b_wins

def win_if_shot(defender):
    """Fold the opening volley's whole casualty distribution into P(defender wins)."""
    with game.turn().shooting() as shooting:
        opening = shooting.volley(game.field(defender, 10), game.field(lions, 10), distance=10)
    return sum(p * win_given_charge(defender, 10 - k)      # mix over every outcome...
               for k, p in enumerate(opening.casualties))  # ...weighted by its probability

for slug in ("sisters-of-avelorn", "elven-archers"):
    defender = game.units[slug]
    print(defender.name,
          win_given_charge(defender, 10),  # shoot elsewhere: Lions charge at full strength
          win_if_shot(defender))           # shoot the Lions first: the volley folded in
```

The script prints the same two numbers per unit, with the volley's distribution alongside:

```
  Sisters of Avelorn (BS 5, 8-shot volley, Lions save 6+):
    opening volley fells (of 10):  0:2%  1:12%  2:24%  3:28%  4:21%  5:10%  6:3%
    shoot elsewhere — Lions charge at full strength:  P(win) 0.298
    shoot the Lions first (volley folded in):         P(win) 0.731   (+0.434)

  Elven Archers (BS 4, 8-shot volley, Lions save 4+):
    opening volley fells (of 10):  0:19%  1:35%  2:28%  3:13%  4:4%  5:1%
    shoot elsewhere — Lions charge at full strength:  P(win) 0.044
    shoot the Lions first (volley folded in):         P(win) 0.179   (+0.135)
```

Same board, same threat, opposite advice. For the **Sisters**, shooting first is decisive — it turns a combat they mostly lose (0.298) into one they mostly win (0.731). They can, because they both shoot well and hold the line: the Bow of Avelorn is magical, so a White Lion's **Lion Cloak** can't better its save (the Lions weather it on 6+), and in the melee Strike First, light armour, and a Stand & Shoot that scores for them let the thinned charge be beaten. For the **Archers**, shooting the Lions barely matters (0.044 → 0.179) — they lose the combat almost regardless. A plain longbow leaves the Lion Cloak up (Lions save 4+, so far fewer fall), and WS 4 with no armour and no Strike First loses the melee whatever charges in. Their arrows are better spent on a target they can actually break; these Lions will roll them either way.

Notice both numbers are the *whole spread* folded in — for the Sisters, the 2% chance of felling none and the 3% chance of felling six both weighed, not a rounded mean standing in for them. And one thing the engine does *not* yet do shows exactly where: the Stand & Shoot chains into the melee for free — `fight` enters the charger already thinned by the reaction and scores its wounds toward the combat result — but that is the *same* combat. The opening volley is a *previous turn*, whose wounds must not score this combat, so it is folded here as the mixture above rather than handed to `fight` as prior losses. The missing primitive is a way to enter a combat thinned-but-unscored (a cross-turn battle layer); until then, the mixture is the honest fold, and it is exact.

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
