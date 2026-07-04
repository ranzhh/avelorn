# Avelorn

A toolkit for tabletop wargames, starting with **Warhammer: The Old World**.

It comes down to three things, all built on one curated dataset. The first is a unit and army database you can query. The second is an army-list planner that knows the rules well enough to catch an illegal list. The third is a battler that works out combat odds, and rather than rolling dice thousands of times and averaging the results, it computes the exact distribution. That lets it answer the questions a game actually hinges on, like the odds a unit breaks and runs, instead of just handing back a mean.

The data is hand-authored YAML under `data/`, and that is the single source of truth. Special rules are data too, so they compile into the dice walk instead of living as hard-coded special cases.

## What's built so far

The dice engine is the part that works today.

- **Schema** (`tow/schema`) models units, weapons, armour, and rules as Pydantic types, validated as they load from YAML; `TOWRepository` (`tow/data`) is the one place that knows the `data/` tree's layout and hands back the loaded registries.
- **Combat math** (`tow/combat`) resolves the shooting chain end to end, from to-hit through to-wound to the armour save, and returns an exact casualty distribution built on the hit/wound/save charts. Special-rule effects fold into the dice walk straight from the data, and an engagement context (did the unit move? how far to the target?) gates the situational modifiers.
- **Close combat** resolves a full round on the same engine: both sides strike in Initiative order, casualties tally into a combat result, and the loser takes its break test. The **charge sequence** composes into it — a unit charges, the target reacts with Stand & Shoot, and the survivors fight — all as exact distributions.
- **Panic tests** take a casualty distribution and return the exact chance the target is forced to test, then holds, falls back, flees, or is wiped out.
- **Querying** lets you ask for a specific outcome, such as `at least`, `at most`, `exactly`, or `between` over a named variable, and hands back its probability.
- **Army-list entries**: a `Complement` sizes and equips a datasheet — a chosen model count and options, validated against what the unit is allowed to take — and derives its points and effective loadout. It is the first piece of the list planner.
- **Importer** pulls units off tow.whfb.app into the `data/` tree (see credits).

The rest is still to come, roughly in the order it matters.

- **More army data.** Three High Elf units exist today, which is enough to exercise the engine but nowhere near a playable database. Filling this out is what the importer is for.
- **A backing store.** Everything loads from YAML on each run right now. The plan is to load that YAML into SQLite once and query it from there, so the database can grow past what you would want to parse from files every time.
- **The query API.** This is an HTTP (and MCP) surface over that store, so the unit and army database becomes reachable from something other than a Python import. It is the queryable half of the goal.
- **The list planner.** You build an army list and have it checked against the rules: points limits, army composition, and unit availability. The per-unit half exists as `Complement`; what is missing is the composition above it.
- **The magic phase.** The exact dice walk underneath is generic — shooting and close combat are its first two callers — so what is missing is the phase resolver rather than the maths.

## Demo: one unit shoots another

`scripts/shooting_demo.py` wires the whole chain together end to end. Sketched out:

```python
from avelorn.tow.combat.context import EngagementContext
from avelorn.tow.combat.morale import make_panic_tests
from avelorn.tow.combat.query import Comparator, Predicate, query_result
from avelorn.tow.combat.shooting import shoot_unit
from avelorn.tow.data import TOWRepository

# The repository knows the data/ tree, the YAML source of truth.
repo = TOWRepository()
archers  = repo.units["elven-archers"]
spearmen = repo.units["elven-spearmen"]
longbow  = repo.weapons["longbow"]

# 10 archers, moving, shoot a 20-strong unit at 18".
result = shoot_unit(
    archers, spearmen,
    shooters=10, weapon=longbow,
    armoury=repo.armoury, rules=repo.rules,
    context=EngagementContext(moved=True, distance=18),
    defenders=20,
)

print(f"to hit {result.hit_target}+ / to wound {result.wound_target}+")
print(f"expected casualties: {result.expected_casualties:.2f}")

# Exact distributional queries: not the average, the actual odds.
wiped    = query_result(result, "survivors", Predicate(Comparator.EXACTLY, 0))
any_kill = query_result(result, "casualties", Predicate(Comparator.AT_LEAST, 1))
print(f"P(at least one falls): {any_kill:.3f}   P(wiped out): {wiped:.3f}")

# Does the shooting break them?
panic = make_panic_tests(result, spearmen, rules=repo.rules)
print(f"P(flees): {panic.p_flees:.3f}   P(holds): {panic.p_holds:.3f}")
```

Run it as-is (with defaults) via `make demo`, or drive it directly:

```sh
uv run python scripts/shooting_demo.py 10 elven-archers elven-spearmen 20 --moved --distance 18
```

Add `-v` for the full DEBUG math trace on stderr.

`scripts/melee_demo.py` and `scripts/charge_demo.py` do the same for a round
of close combat and for the full charge sequence (Stand & Shoot included).

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
