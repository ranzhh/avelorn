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
- **The command line** (`cli`) is a window on the database, grouped by what it reads: `avelorn units list` and `avelorn units show <slug>`, `avelorn rules list` and `avelorn rules show <slug>`. `avelorn rules list --unmodelled` reports every rule the corpus prints that the engine does not apply -- the per-action "not factored" notes, totalled. Nothing the engine *resolves* is a flag — a volley, a combat round, a break test, a folded question spanning two turns. The vocabulary for posing those is still to be designed, and mirroring each resolver's signature into options would fix the wrong shape in place.
- **The HTTP surface** (`api`) is the same window over the wire: `GET /units`, `GET /units/{slug}`, `GET /rules`, `GET /rules/{slug}` and `GET /rules/unmodelled`, plus `POST /muster`, which sizes and equips one datasheet and hands back what the block costs. The responses are the schema types themselves, so the OpenAPI document at `/docs` is generated from the same models the YAML validates against. `make serve` runs it. Both surfaces show a unit through one declared view (`tow/views`), so neither can fall behind the other.
- **Army-list entries**: a `Complement` (`tow/muster`) sizes and equips a datasheet — a chosen model count and options, validated against what the unit is allowed to take — and derives its points and effective loadout. It is the first piece of the list planner.
- **The front end** (`frontend`) is a SvelteKit browser over that HTTP surface: the datasheet list, filterable, one datasheet in full, and the rule entries its special rules link to -- a rule the engine does not model is marked as such rather than linked. It also builds an army list: pick a datasheet, size it, tick the options it offers, and `POST /muster` costs the block. A block stays editable -- reopen it to change the model count or the wargear and it is recosted, or duplicate it to take the same unit again -- and an open block shows the loadout it actually ends up with, the chosen options folded in. Nothing there checks whether the list is *legal* — army composition is not modelled yet — so it totals blocks and refuses only what a datasheet itself forbids. The list lives in the browser, since there is no store behind the API to keep it in. Its TypeScript types are generated from the API's OpenAPI document (`make types`), so the Pydantic schema stays the only place a unit's shape is written down.
- **The development stack** (`compose.yaml`) brings both up together with `make up`, the source bind-mounted so each still reloads on an edit. The native path is unchanged: `make serve` and `make frontend` run the same two processes without Docker.
- **Importer** pulls units off tow.whfb.app into the `data/` tree (see credits).

The rest is still to come, roughly in the order it matters.

- **More army data.** A handful of High Elf units exist today, which is enough to exercise the engine but nowhere near a playable database. Filling this out is what the importer is for.
- **A backing store.** Everything loads from YAML on each run right now. The plan is to load that YAML into SQLite once and query it from there, so the database can grow past what you would want to parse from files every time.
- **The query API.** This is an HTTP (and MCP) surface over that store, so the unit and army database becomes reachable from something other than a Python import. It is the queryable half of the goal. The `cli` and `api` routes above are its first slice, over the YAML tree rather than the store; what is missing is the store beneath and the MCP surface beside.
- **A question vocabulary.** What a caller — the CLI, the API, an agent — poses to the engine, and what comes back. `tow/query` has the operators (`at least`, `at most`, ...) but the questions are still named after the engine's own variables, so asking one means knowing how the resolver is shaped. Until this exists, resolutions stay reachable from Python and the demo scripts only.
- **The list planner.** You build an army list and have it checked against the rules: points limits, army composition, and unit availability. The per-unit half exists as `Complement`; what is missing is the composition above it.
- **The magic phase.** The exact dice walk underneath is generic — shooting and close combat are its first two callers — so what is missing is the phase resolver rather than the maths.

## The kind of thing you can ask it

The engine models **distributions, not averages**, and the good questions come from folding those distributions together. Here's one, with a twist: the answer depends on which unit is asking.

**White Lions of Chrace** are 10" away and will charge you next turn no matter what. This turn you can shoot them, or shoot something else. Either way they charge, you Stand & Shoot as they close, and you fight. So: **does shooting them first improve your odds in that combat?** Ask it for two units — elite **Sisters of Avelorn** and plain **Elven Archers** — and you get opposite answers.

The volley doesn't fell "about three" Lions. It fells a *spread*, and each outcome is a different charge into a different combat. So the honest answer folds every branch, weighted by how likely it is — that fold is `Distribution.bind`, not an enumerate-and-sum (`scripts/soften_the_charge_demo.py`):

```python
from enum import Enum, auto

from avelorn.core.distribution import Distribution
from avelorn.tow.contingent import Charge, ChargeArc
from avelorn.tow.game import TOWGame
from avelorn.tow.phases.movement import StandAndShoot

game = TOWGame.load_data()
lions = game.units["white-lions-of-chrace"]

class Side(Enum):
    CHARGER, DRAW, DEFENDER = auto(), auto(), auto()

def win(defender, charging):
    """Who wins when `charging` Lions charge — a Distribution over the outcome."""
    if charging == 0:
        return Distribution.pure(Side.DEFENDER)
    lions_unit = game.field(lions, charging).wielding("Chracian Great Blade")
    unit = game.field(defender, 10).wielding("Hand Weapon")
    turn = game.turn()
    with turn.movement() as movement:
        engagement = movement.charge(lions_unit, unit, Charge(10, ChargeArc.FRONT))
        engagement.react(StandAndShoot())   # thins the chargers AND scores — folded natively
    with turn.combat() as combat:
        r = combat.result(combat.fight(engagement))
        return Distribution({Side.CHARGER: r.p_a_wins, Side.DRAW: r.p_draw, Side.DEFENDER: r.p_b_wins})

def win_if_shot(defender):
    """Fold the opening volley's whole casualty distribution into the combat."""
    with game.turn().shooting() as shooting:
        opening = shooting.volley(game.field(defender, 10), game.field(lions, 10), distance=10)
    return (Distribution.from_counts(opening.casualties)   # felled
            .map(lambda felled: 10 - felled)               # surviving chargers
            .bind(lambda n: win(defender, n))              # the combat, folded onto each
            .prob(lambda s: s is Side.DEFENDER))

for slug in ("sisters-of-avelorn", "elven-archers"):
    defender = game.units[slug]
    print(defender.name,
          win(defender, 10).prob(lambda s: s is Side.DEFENDER),  # shoot elsewhere: full strength
          win_if_shot(defender))                                 # shoot the Lions: volley folded in
```

The script prints the same two numbers per unit, with the volley's distribution alongside:

```
  Sisters of Avelorn (BS 5, Lions save 6+):
    opening volley fells (of 10):  0:2%  1:12%  2:24%  3:28%  4:21%  5:10%  6:3%
    shoot elsewhere:       P(win) 0.298
    shoot the Lions first: P(win) 0.731   (+0.434)

  Elven Archers (BS 4, Lions save 4+):
    opening volley fells (of 10):  0:19%  1:35%  2:28%  3:13%  4:4%  5:1%
    shoot elsewhere:       P(win) 0.044
    shoot the Lions first: P(win) 0.179   (+0.135)
```

Same board, same threat, opposite advice.

**Sisters:** shooting first flips the fight, 0.298 → 0.731. They can afford to, because they shoot well *and* fight well. The Bow of Avelorn is magical, so a White Lion's **Lion Cloak** can't help (the Lions save on 6+), and in the melee Strike First, armour, and a Stand & Shoot that scores for them beat the thinned charge.

**Archers:** it barely matters, 0.044 → 0.179. A plain longbow leaves the Lion Cloak up (Lions save 4+, so far fewer fall), and WS 4 with no armour loses the melee regardless. Their arrows are better spent on a target they can actually break.

Both numbers fold the whole spread, not a rounded mean. One caveat, honest about the engine: the Stand & Shoot chains into the melee for free — `fight` enters the charger already thinned and scores its wounds. The opening volley can't, because it's a previous turn and its wounds mustn't score *this* combat, so it's folded as the mixture above instead. Letting a unit enter a combat thinned-but-unscored is the one piece still missing.

Run it via `make demo DEMO=soften_the_charge`, or drive it directly:

```sh
uv run python scripts/soften_the_charge_demo.py   # no arguments — run and read
```

Add `-v` for the full DEBUG math trace on stderr.

Three more demos, each a "did you know?" in a few lines: `shooting_demo.py` (two units shoot one target; their tolls compose in a single `bind`), `melee_demo.py` (charging can be worse than receiving — the charger's ranks lapse), and `turn_demo.py` (walk a whole player-turn phase by phase). Each is `scripts/<name>_demo.py`, runnable as `make demo DEMO=<name>`.

## Getting started

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
git clone <repo> && cd warhammer
make install   # uv sync + install the pre-commit hooks
make test      # run the suite
make demo      # end-to-end shooting demo from the data files
make lint      # ruff + ty + hygiene hooks over the whole tree
make serve     # serve the unit database at http://127.0.0.1:8000 (docs at /docs)
```

Then `uv run avelorn units list` to see what the corpus holds, `uv run avelorn units show <slug>` to read a datasheet, and `uv run avelorn rules list --unmodelled` to see what the engine is not yet applying.

## Credits

Unit data is imported from **[tow.whfb.app](https://tow.whfb.app)**, an
excellent community reference for The Old World. Thanks to its author,
**@FlammableHero**, for building and maintaining it.
