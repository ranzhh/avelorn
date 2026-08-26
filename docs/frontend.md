# The front end

A tool for asking the engine exact questions about units on a table, modelled on
Path of Building and poe.ninja. Dark, dense, numbers first.

## Rules that got a previous attempt scrapped

1. **No prose the model wrote.** Every string on screen is a control label, a
   value, or something the API returned. No captions narrating a chart, no
   editorial. A refusal shows the API's own `detail`.
2. **Never invent a derivation.** If the API does not return the operands behind
   a number, the row does not expand.
3. **Desktop only, dark only, for now.** No responsive stacking, no second theme.

## Tokens

All in `frontend/src/app.css`. A component reaching for a raw hex is a bug.

| Role                        | Value                                     |
| --------------------------- | ----------------------------------------- |
| `--plane` / `--panel`       | `#14161a` / `#1b1e23`                     |
| `--sunken` / `--line`       | `#101216` / `#2a2f37`                     |
| `--ink` / `--dim`           | `#dfe3e8` / `#8b939e`                     |
| `--faint`                   | `#5d646d` — 2.79:1, **strokes only**      |
| `--series-1` / `--series-2` | `#3987e5` / `#cf6a5a` — marks, never text |
| `--neutral`                 | `#3a4048` — diverging midpoint            |
| `--ordinal-1`…`-4`          | `#9ec5f4` `#5598e7` `#2a78d6` `#184f95`   |
| `--pos` / `--neg`           | `#7fb069` / `#e08273` — meaning, on text  |
| `--accent` / `--accent-ink` | `#3987e5` fills / `#6fa8dc` text          |

Numbers may wear a meaning colour; that is deliberate, and unusual. Marks carry
identity, text carries meaning.

Colour is computed, not chosen. Re-run on any change, from the dataviz skill:

```
validate_palette.js "#3987e5,#cf6a5a" --mode dark --surface "#1b1e23"
validate_palette.js "#9ec5f4,#5598e7,#2a78d6,#184f95" --ordinal --mode dark --surface "#1b1e23"
```

Two results not worth rediscovering: `#5598e7` fails the dark lightness band
against `#1b1e23`, so it is a ramp step and never a pole. Blue-orange poles
cannot coexist with a red meaning colour — orange against red is ΔE 6.8, under
the floor of 15.

Scale: 4px spacing steps, 13px base, mono and `tabular-nums` on every figure.
Primitives are global classes in `app.css`: `.btn`, `.input`, `.select`,
`.field`, `.check`, `.panel`, `.pill`, `.eyebrow`, `.meta`, `.refuse`,
`.cluster`, `.num`, `.pos`, `.neg`.

## The one route

`/table` owns the app. Deploy dock left, battle table centre, block and resolved
docks right. Docks collapse, remember it, and keep their value on the header row
when shut.

- Clicking a datasheet deploys it at its smallest legal size, then a popover
  beside the block takes the size and options. A row can also be dragged onto
  the table, and what is dragged is a rectangle at the block's real size rather
  than the row.
- Blocks carry a mark — A, B, C — with the model count under it. Icons are
  coming: expect the mark to be replaced by a per-unit icon, so keep whatever
  draws the block label in one place.
- Prices are always what the smallest legal unit costs, suffixed `pts`.
  `UnitSummary.points` is per model, and a bare per-model figure tells you
  nothing about taking the unit. `fielded()` in `listing.ts` does the sum.
- Dragging ghosts the block: it stays put, a dashed ghost follows the pointer,
  an arrow between them carries the reading. **Do not commit the move during the
  drag** — the mover ends up on its target and a charge measures zero. The arrow
  stays after the drop until the next drag.
- Dropped on open table it is a move. Dropped on another block it is an action,
  and the menu offers charge, shoot, or fight-already-joined.
- A side-edge handle re-forms the block. It sends `frontage` to `POST /muster`
  and the engine answers; the browser never computes a formation.
- Facing is any angle, turned by a handle on a stalk. Shift snaps to 15°.
- Nothing is applied back to the table. A result is read, never spent.

## Modules — do not reimplement

`frontend/src/lib/table.ts`, 33 tests. `separation` is edge-to-edge between the
rectangles, zero when they touch or overlap. **Never measure a gap from
`bounds`** — two blocks turned 45° have overlapping boxes while standing apart.
`arc` bounds arcs by the target's own diagonals. Also `corners`, `within`,
`angleTo`, `snap`, `reformed`, `room`, `identifier`.

`frontend/src/lib/charts/scale.ts`, 11 tests. `band` trims a distribution's
negligible tail while keeping the middle contiguous. `Spread` draws one
distribution and takes `compact` for a 74px sparkline. `Outcomes` draws a
stacked bar, `ordinal` or `poles`.

`frontend/src/lib/listing.ts`, 13 tests. Filter and sort for the datasheet list.

## API

Types are generated from the committed OpenAPI document by `make types`. Never
hand-write a response type. No store behind the API: the table lives in the
browser.

- `GET /units` → `UnitSummary` with `armies` (a list).
- `POST /muster` → `MusteredUnit` with `footprint` and `weapons`. Takes an
  optional `frontage`; one wider than the block returns the block's own width.
- `POST /fight`, `POST /volley` → the reports.

## Where it stands

Landed, all stacked and unmerged: #197 tokens, #198 shell, #199 drop-to-resolve,
#200 re-form, #201 deploy-on-click. `/fight`, `/shoot` and `Side.svelte` are
deleted.

Left to do:

1. **Floating panes** for datasheets and rules, Paradox-style: over the table,
   movable, and a rule name inside one opens another pane on top. `/units/[slug]`
   and `/rules/[slug]` stay as routes for linking.
2. **Army list dock**, absorbing the `/list` route.
3. **Two lost inputs.** `hit_modifier` is hardcoded to `0` in
   `routes/table/+page.svelte` — cover, large target, a unit that moved.
   `battle_strength` is never sent, so a target is always treated as fresh.
4. **Derivation, later and not opportunistically.** The goal is that any figure
   opens to its operands, PoB-style. The resolvers report answers, not their
   working, so it is engine work rather than a view change.

## Conventions

Geometry, format and sort logic goes in a `.ts` module with vitest coverage, not
inline in a `.svelte` file. Comments only where the code is hard; never restate
a name.

**Done** means `make frontend-test`, `make frontend-lint`, `make frontend-check`
and `make types-check` clean, `uv run pytest` clean if Python moved, and the
change exercised against a running API.

## Handoff — delete this section when you have read it

Written 2026-08-26 at the end of a long session. Context you will not get from
the code:

- **The design was rejected once, hard.** The first frontend was scrapped whole
  for looking generic. Do not redesign anything without showing it first; build
  a specimen or a prototype wired to the real API and let him pick, one numbered
  decision at a time.
- **Writing style is a live sore point.** A `PreToolUse` hook in his dotfiles
  now holds every commit and PR body once and reads it back at you. One clause
  per sentence, no `X, and Y`, no epigrams, prefer "This PR adds a way to…" over
  describing the object. Re-run the command unchanged to send it.
- **Pointer interactions are never verified.** Nothing here can drive a drag. Say
  so plainly rather than implying it was tested; a real bug shipped that way once
  already.
- **The stack is eight deep and nothing has merged** because GitHub Actions was
  down. Check whether it is back. If it is, the bottom of the stack should land
  before more is piled on. `gh stack` only works from the main worktree — its
  state is in `.git/gh-stack`, and every linked worktree reports "not part of a
  stack".
- Probably next: floating panes, since he was keenest on those and the table
  cannot show a stat line today.
