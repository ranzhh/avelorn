# Avelorn

Avelorn is a toolkit for **Warhammer: The Old World**. It combines a curated rules corpus, exact combat mathematics, and a browser for exploring units, armies, and battles.

The goal is not to estimate a result from thousands of simulated games. Avelorn carries the exact distribution of possible outcomes forward, preserving the branches that matter: casualties, failed tests, charge reactions, combat results, and player choices.

## What is this vibe coded bullshit?

I am a big fan of writing clean and concise code. LLMs have proven to help me massively at work, but they definitely don't produce the best code on the first try without steering; maybe that will change in the future.

This project is an attempt to write code for what I know to be a very hard endeavour - mapping a game with hooks and rules that interact with each other - using only LLMs. As of now, the only piece of the codebase I have touched by hand is this README, and even then just the parts until now.

I believe that in order for me to get better at using LLMs, a project such as this - forcing me to wrestle with their inherent weaknesses - will massively help. I hope to become better at planning before prompting and properly steering these models.

The tooling used so far is Claude Code + Claude Opus 4.8 and Claude Fable 5. If you're going to dive into this project, thanks for sticking it out so far! The fun part begins now.

## What you can do today

### Explore the corpus

Units, weapons, armour, and special rules live in validated YAML under `data/`. The same models power the Python API, command line, and OpenAPI documentation.

```sh
uv run avelorn units list
uv run avelorn units show white-lions-of-chrace
uv run avelorn rules list --unmodelled
```

### Muster units and resolve battles

A datasheet can be fielded with a chosen size and loadout. The existing phase resolvers can then calculate:

- shooting volleys and the panic they cause;
- a full round of close combat, including Initiative order, casualties, combat result, and Break tests;
- charges, including charge reactions and Stand & Shoot;
- exact probabilities for named outcomes, rather than only averages.

The demo scripts are small, runnable examples of the engine:

```sh
make demo DEMO=shooting
make demo DEMO=melee
make demo DEMO=soften_the_charge
make demo DEMO=turn
```

A useful question is not simply “how many casualties should I expect?” It is “does shooting this unit first improve my chance of winning the combat?” Avelorn can fold the entire shooting distribution into the later charge and combat, so every possible number of survivors reaches the appropriate fight with its own probability.

### Use the browser and HTTP API

The API exposes corpus reads plus operations for mustering, volleys, and fights. The frontend provides:

- unit, weapon, armour, and rule browsers;
- army-list entries with costs and resolved equipment;
- a battle table where units can be deployed, moved, re-formed, and engaged;
- result panes showing full outcome distributions;
- a pane for every printed datasheet, weapon, armour entry, and rule.

Start the native development stack with:

```sh
make serve       # API at http://127.0.0.1:8000, docs at /docs
make frontend    # browser at http://localhost:5173
```

Or run both services in containers:

```sh
make up
```

The battle table is available at [localhost:5173/table](http://localhost:5173/table).

## The graph compiler

The next layer turns a Warhammer procedure into a static program of named rulebook steps. A program describes the shape of a sequence; evaluation supplies the distributions and player choices.

The graph core can currently:

- represent measurements, decisions, rolls, and consequences as typed steps;
- validate step scope and kernel arity while building a program;
- represent repeated groups, fixed slots, and decision lanes;
- preserve joint outcomes in execution traces, so correlated results are not reconstructed from independent marginals;
- defer repeated-group aggregation until a projection is read, with an explicit monoid identity for zero repetitions;
- attach rule nodes to the steps they land on and record whether a landing was applied, honoured, held, or inapplicable;
- serialize an evaluated program into the shape consumed by the graph frontend.

The graph frontend is available at `/graph`. It lays out steps left to right, draws groups as frames, displays readings on edges, and connects rule nodes to their landings. The current graph work is deliberately a foundation: program loading from YAML and rule effects are the next layers, and the existing shooting and combat resolvers remain the production game surface while that migration proceeds.

The design is documented in [`DESIGN-GRAPH.md`](DESIGN-GRAPH.md) and the printed step vocabulary in [`DESIGN-GRAPH-rules.md`](DESIGN-GRAPH-rules.md).

## Project shape

- `src/avelorn/tow/schema` — validated corpus models.
- `src/avelorn/tow/data.py` — the repository and YAML loader.
- `src/avelorn/tow/game.py` and `src/avelorn/tow/contingent.py` — loaded games and fielded units.
- `src/avelorn/tow/engine` — exact dice, attack, casualty, and rule calculations.
- `src/avelorn/tow/phases` — shooting, combat, movement, and strategy callers.
- `src/avelorn/core/distribution.py` — the reusable exact-distribution machinery.
- `src/avelorn/core/graph.py` — the graph-program execution core.
- `frontend` — the SvelteKit browser and graph view.
- `scripts` — end-to-end examples and corpus tooling.

## Development

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node for the frontend.

```sh
make install
make test
make lint
make frontend-test
make frontend-check
```

The project is being built with substantial assistance from coding agents. That makes the tests, pinned demo output, explicit designs, and rule-source links particularly important: the engine should be explainable, reproducible, and honest about what it does not model yet.

## Data and credits

Unit data is imported from [tow.whfb.app](https://tow.whfb.app), an excellent community reference for The Old World. Thanks to its author, **@FlammableHero**, for building and maintaining it.
