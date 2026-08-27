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

One stack, unmerged: #197 tokens, #198 shell, #199 drop-to-resolve, #200
re-form, #201 deploy-on-click. `/fight`, `/shoot` and `Side.svelte` are deleted.

Four siblings off #201, unmerged and independent of each other. Each conflicts
with the others in `routes/table/+page.svelte` only.

- **#202 floating panes.** `panes.ts` places them, `Pane.svelte` is the chrome,
  `Sheet.svelte` and `RuleText.svelte` are the bodies. `/units/[slug]` and
  `/rules/[slug]` stay as routes for linking.
- **#203 the To Hit ledger.** A compiled `Modifier` carries the rule that
  emitted it. `engine/derivation.py` gathers the target's operands. Shooting
  only.
- **#204 matchup matrix.** Every standing block against every other, under the
  table. Depends on the roster, not on where a block stands.
- **#205 conditions dock.** The `moved` flag reaches `POST /volley` at last, so
  Moving and Shooting can fire. The situational stepper and battle strength go
  with it.

Left to do:

1. **Army list dock**, absorbing the `/list` route.
2. **Derivation past the To Hit roll.** #203 does one target of four in one
   phase of two. A melee round reports no ledger; giving it one means threading
   the same shape through `phases/combat.py`.
3. **Named situational modifiers.** #205's stepper is deliberately unnamed:
   cover and large target have no entry in the corpus, so a label would assert
   a rulebook value nothing here can check. Import those rules and the dock can
   offer real toggles.

## Conventions

Geometry, format and sort logic goes in a `.ts` module with vitest coverage, not
inline in a `.svelte` file. Comments only where the code is hard; never restate
a name.

**Done** means `make frontend-test`, `make frontend-lint`, `make frontend-check`
and `make types-check` clean, `uv run pytest` clean if Python moved, and the
change exercised against a running API. `pre-commit run -a` skips untracked
files, so stage before you trust it.

Pointer interactions are drivable: Playwright's browsers are cached under
`~/.cache/ms-playwright`. Grab a block by its `rect`, never by the `g`, whose
box grows by the rotation stalk once the block is picked.
