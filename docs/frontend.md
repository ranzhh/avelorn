# The front end

A build spec, written so an agent joining with no conversation history can take
one slice and produce something that fits beside the others. Decisions here are
settled unless the Open questions section says otherwise.

## What it is

A tool for asking the engine exact questions about units on a table, modelled on
Path of Building and poe.ninja. Dense, dark, numbers first. Tables and figures
are the primary surface; chrome recedes.

## Hard rules

These are the ones that got a previous attempt scrapped whole. They are not
style preferences.

1. **No prose the model wrote.** Every string on screen is a control label, a
   value, or something the API returned. No explanatory sentences, no captions
   narrating what a chart shows, no editorial ("a near-even fight"). A refusal
   shows the API's own `detail`.
2. **Function before form.** A change is judged on what it lets you do. Ship
   behaviour wired to the real API rather than a mock.
3. **Never invent a derivation.** If the API does not return the operands behind
   a number, the row does not expand. A plausible-looking breakdown that the
   engine did not produce is worse than no breakdown.
4. **Desktop only for now.** Do not trade density for a phone. No responsive
   stacking; assume a wide viewport.
5. **Dark only for now.** One theme. The token block is structured so a light
   theme is a second block, but do not add one yet.

## Tokens

Dark only. Every colour, space and size comes from `frontend/src/app.css`; a
component that reaches for a raw hex has a bug.

### Surfaces and ink

| Role       | Value     | Notes                                                                  |
| ---------- | --------- | ---------------------------------------------------------------------- |
| `--plane`  | `#14161a` | page                                                                   |
| `--panel`  | `#1b1e23` | panels, and the chart surface the palette is validated against         |
| `--sunken` | `#101216` | inputs, derivation rows, table stripes                                 |
| `--line`   | `#2a2f37` | borders, gridlines, hairlines                                          |
| `--ink`    | `#dfe3e8` | primary text — 12.96:1 on panel                                        |
| `--dim`    | `#8b939e` | secondary text, table headers — 5.38:1                                 |
| `--faint`  | `#5d646d` | **non-text only** — 2.79:1, fails body text. Carets, hairline strokes. |

### Marks — identity and order

Used on bars, segments and table rectangles. Never on text.

| Role                 | Value                                               |
| -------------------- | --------------------------------------------------- |
| `--series-1`         | `#3987e5`                                           |
| `--series-2`         | `#cf6a5a`                                           |
| `--neutral`          | `#3a4048` (diverging midpoint; a grey, never a hue) |
| `--ordinal-1` … `-4` | `#9ec5f4` `#5598e7` `#2a78d6` `#184f95`             |

### Meaning — on numbers

A figure may wear a meaning colour. This is a deliberate departure from the
usual rule that numbers stay neutral; it is how Path of Building reads.

| Role           | Value     | Contrast on panel                       |
| -------------- | --------- | --------------------------------------- |
| `--pos`        | `#7fb069` | 6.62:1                                  |
| `--neg`        | `#e08273` | 6.06:1                                  |
| `--accent-ink` | `#6fa8dc` | 6.61:1 — accent _text_ and links        |
| `--accent`     | `#3987e5` | 4.59:1 — accent _fills_ and focus rings |

`--neg` is a lighter step than `--series-2` on purpose: mark-red and text-red are
the same hue at different steps, so the channel is never ambiguous. Where a
meaning colour is the only thing separating two figures, pair it with a sign or a
label so it degrades rather than disappears.

### Validation

Colour is computable, so it is computed. Re-run these on any change, from the
dataviz skill's `scripts/`:

```
validate_palette.js "#3987e5,#cf6a5a" --mode dark --surface "#1b1e23"
  → PASS. protan ΔE 20.9, normal-vision ΔE 27.1, both ≥3:1 on surface.
validate_palette.js "#9ec5f4,#5598e7,#2a78d6,#184f95" --ordinal --mode dark --surface "#1b1e23"
  → PASS. monotone, ΔL gaps ≥0.06, light end 2.06:1.
```

Two results worth not rediscovering: `#5598e7` fails the dark lightness band
against `#1b1e23` (L 0.671, band tops at 0.67), so it is a ramp step and not a
pole. And blue↔orange poles cannot coexist with a red "bad" — orange vs red
measures ΔE 6.8 unsimulated, below the 15 floor. Hence blue↔red poles, with
meaning red as a separate step.

### Scale

Space on a 4px base: `--space-1` `0.25rem` through `--space-6` `2rem`. Type:
`--text-xs` `0.6875rem`, `--text-sm` `0.75rem`, `--text-base` `0.8125rem`,
`--text-lg` `0.9375rem`, `--text-xl` `1.125rem`. Base is 13px — the density is
the point. `--font-mono` on every figure; `font-variant-numeric: tabular-nums`
in any column that aligns vertically.

## Primitives

Global classes in `app.css`, not components: the same button everywhere is the
point of a system. `.btn` (`.btn-primary`, `.btn-ghost`, `.btn-sm`), `.input`,
`.select`, `.field`, `.check`, `.panel`, `.pill`, `.eyebrow`, `.refuse`,
`.cluster`, `.num`, `.meta`, `.pos`, `.neg`. Layout stays in scoped component
CSS.

## Composition

One route. The battle table is the primary surface and owns the screen.

```
┌───────────────────────────────────────────────────────┐
│ header: app name · unmodelled count · latency         │
├────────────┬──────────────────────────────┬───────────┤
│ config     │                              │ results   │
│ (docked)   │        battle table          │ (docked)  │
│            │                              │           │
│ army list  │                              │           │
│ (docked)   │                              │           │
└────────────┴──────────────────────────────┴───────────┘
```

- Docked panels are collapsible. **A collapsed panel keeps the value it carries
  on its header row** — `Elven Archers ×20`, `14 shots, 2.33 felled` — so
  collapsing costs space, not information. Open state persists per panel.
- `/list` as a route disappears; the army list is a docked panel.
- Datasheets and rule entries open as **floating panes**, Paradox-style: a pane
  over the table, movable, dismissible, and a rule name inside one opens another
  pane on top. Panes stack. `/units/[slug]` and `/rules/[slug]` stay as routes:
  they are useful on their own and remain linkable. The panes are the primary way
  in, not the only one.

## Interaction on the table

- Blocks are drawn at their true footprint from `MusteredUnit.footprint` —
  `files` × `ranks` on the datasheet's base size.
- **Clicking a datasheet deploys it** at its smallest legal size, on the near
  edge facing up, moved clear of anything already standing there (`room`). Size
  and options are then chosen from a popover next to the block, against
  something you can see, rather than from a form in the panel. Dragging a row
  from the panel onto the table deploys it where it is dropped.
- **A block is named, not counted.** Each carries a progressive mark -- A, B, C
  -- with its model count under it. Two blocks of twenty are otherwise
  indistinguishable.
- **Drag ghosts the block.** It stays where it stands while a dashed ghost
  follows the pointer, with an arrow between them and the reading live on the
  arrow. A step that would put a corner off the table is refused, so the ghost
  stops against the edge rather than the pointer running away from it.
- **Where the ghost is dropped decides what happened.** On empty table it is a
  move and the block goes there. On another block it is an action, the mover
  stays put, and the menu opens: charge, shoot if it carries a missile profile,
  fight already-joined.
- Committing the move during the drag is the bug this shape avoids. The mover
  would end up on top of its target, and the gap a charge must cover would
  measure zero.
- **The arrow stays after the drop**, dashed and dimmer than the live one, with
  its reading. One at a time: it is cleared by the next drag, and by a block
  arriving or leaving, which would make it a lie about the table.
- **Resize changes the frontage.** A picked block carries a handle on each side
  edge. Dragging one reads a file count off how far the pointer is along the
  block's own width, previews the new rectangle, and on release asks
  `POST /muster` for the footprint that width actually takes. The browser never
  decides the formation: `frontage` goes to the API and the engine's `Formation`
  answers. Model count is not a drag; it is changed from the block's popover.
  The handles are drawn filled and gripped rather than outlined -- at table
  scale a hairline handle cannot be found.
- **Facing is any angle**, turned by a rotation handle on a stalk off the block's
  front, the way Word and PowerPoint rotate a shape. Free by default; Shift
  snaps to 15°. Because a block can sit off the axis, nothing may measure it
  from its bounding box.
- Selection uses the mark poles: the picked block takes `--series-1`, the one
  being asked about takes `--series-2`.
- Nothing is applied back onto the table. A result is read, never spent: the
  routes return distributions, and carrying one forward means collapsing it to a
  single number. That collapse is where a battle simulator starts and this is
  not one.

## Geometry

`frontend/src/lib/table.ts`, under 26 tests. Blocks turn to any angle, so this
works in polygons rather than boxes.

- `corners` gives the four corners at any facing; `bounds` is their axis-aligned
  box, for hit areas and edge checks only.
- `separation` is edge-to-edge in inches between the rectangles themselves, zero
  when they touch or overlap, including when one sits wholly inside another.
  Never measure a gap from `bounds` — two blocks turned 45° have overlapping
  boxes while standing well apart.
- `arc` bounds the arcs by the target's own diagonals, so a wide block presents a
  wide front and one stood on end presents a wide flank.
- `angleTo` and `snap` back the rotation handle. `room` finds a free spot for a
  newly deployed block.

Do not reimplement any of it.

## Charts

`frontend/src/lib/charts/`. `scale.ts` holds the arithmetic under 11 tests:
`band` trims a distribution's negligible tail while keeping the middle
contiguous, `ticks` gives round percentage steps, `percent`/`exact` format,
`labelEvery` thins colliding axis labels.

- A distribution is drawn: one column per outcome, mean marked, bars capped at
  24px with a 2px surface gap, square at the baseline and 4px-rounded at the
  data end. Single series, so no legend.
- Ordered outcomes (break test, panic test) are one stacked bar on the ordinal
  ramp, light for the best outcome to dark for the worst, 2px surface gaps
  between segments and no borders.
- `A wins / draw / B wins` is a diverging bar: poles on the two series colours,
  the draw on `--neutral`.
- `Spread` draws one distribution, and takes `compact` for the 74px sparkline
  form that fits inside a table row.
- `Outcomes` draws one stacked bar, `ordinal` for outcomes that worsen and
  `poles` for two sides about a neutral middle.
- Every chart has a table twin. A value is never reachable only by hovering.

## Derivation — the direction, not the next task

The goal is that any figure opens to its operands, and those to theirs: a to-hit
target back to the BS, the range band and each modifier. **Do not build this
opportunistically.** The resolvers currently report answers, not their working,
so it is engine work rather than a field added to a view. Until it lands, the
frontend chain stops where the returned fields stop and rows that cannot be
broken down are left unexpandable.

What is already derivable from `VolleyReport`: `shots`, `hit_target`, `p_hit`,
`wound_target`, `p_wound`, `save_target`, `ward_target`, `p_unsaved`,
`expected_wounds`, `expected_casualties`. Laying those out as the sequence the
engine walks is honest and needs no backend change.

## API facts a slice will need

- `GET /units` → `UnitSummary`, carrying `armies` (a list — a datasheet may be
  filed under several).
- `POST /muster` → `MusteredUnit`, carrying `footprint` (`files`, `ranks`,
  `width_mm`, `depth_mm`; null where a datasheet prints no base size) and
  `weapons` as `Wieldable` with `fights` and `shoots`. It takes an optional
  `frontage`, which re-forms the block that many models wide and changes the
  footprint without changing the cost. A frontage wider than the block comes
  back as the block's own width, so a caller may send what it dragged to.
- `POST /fight`, `POST /volley` → the reports. Both take a `Deployment` per side
  with an optional `weapon` and `frontage`; omitting `weapon` lets the API pick
  the last one usable in that phase.
- Types are generated from the committed OpenAPI document by `make types`. Never
  hand-write a response type.
- No store behind the API. The army list and the table live in the browser.

## Work breakdown

Each is independently reviewable and lands on its own. Later ones assume earlier
ones, so a parallel agent should take a slice with its dependencies already
merged or accept a rebase.

1. **Tokens and primitives, alone.** `app.css` plus one page proving it. No
   restructuring. ← _in progress, this branch_
2. **The one-route shell.** Docked collapsible panels with header values and
   persisted open state; the battle table as a static surface with blocks placed
   by click. No drag. ← _landed_
3. **Drag.** Move a block, drop onto another to open the action menu, drag a side
   edge to re-form. ← _landed_
4. **The result panels.** Fight and volley resolved into the docked panel, with
   the stat chain, distributions and outcome bars. ← _landed_
5. **Floating panes.** Datasheet and rule panes, stacking, hyperlinked.
6. **The army list panel.** Absorbs the `/list` route.

## Conventions

- Sort/filter/geometry/format logic goes in a `.ts` module with vitest coverage,
  not inline in a `.svelte` file. `make frontend-test` runs it and CI has a step.
- Comments: one line, only where the code is genuinely hard. Never restate a
  name.
- **Done** means: `make frontend-test`, `make frontend-lint`, `make
frontend-check` and `make types-check` all clean, `uv run pytest` clean if
  anything Python moved, and the change exercised against a running API — not
  tests alone.

## What the old routes are waiting for

`/fight`, `/shoot` and `Side.svelte` are gone: the table resolves both now.
`/list` goes in slice 6, when the army list becomes a dock.

## Open questions

- **Light theme** — deferred, not refused.
