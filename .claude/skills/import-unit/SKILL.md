---
name: import-unit
description: Import one Warhammer - The Old World unit into the Avelorn corpus end to end - the datasheet, the weapons and armour it needs, effects for any rule that folds into the maths - then open a PR listing only what is unmodelled. Use when asked to import, add or land a named unit ("import Swordmasters of Hoeth", "/import-unit white-lions-of-chrace", "have a subagent import the Phoenix Guard").
---

# Import one unit, end to end

The unit is named in the arguments, as a slug or a display name. Resolve a
display name to the site's slug by lowercasing and hyphenating
("Swordmasters of Hoeth" -> `swordmasters-of-hoeth`).

One unit per run. The deliverable is a PR whose description lists only what is
unmodelled and why.

## Work in your own checkout

The main session and any parallel agent share one working tree, and a branch
switch in either yanks the ground out from under the other -- uncommitted
imports included. So:

- **Running this as a subagent:** you should have been launched with
  `isolation: "worktree"`. If your working directory is the repo root rather
  than a path under `.claude/worktrees/`, say so and stop; ask to be relaunched
  isolated rather than racing whoever else is in there.
- **Dispatching this to a subagent:** pass `isolation: "worktree"`.
- **Running it yourself in the main session:** check `git worktree list` and
  `git status` first. If anything else is live in the tree, use EnterWorktree.

Run everything with `uv run` from your own root, never another checkout's.

## Survey before you touch anything

Read what the unit needs before importing, so a blocker is found in one pass
rather than four:

```python
from avelorn.tow.importers.whfb_app.client import WhfbAppClient
from avelorn.tow.importers.whfb_app.parse import parse_unit
from avelorn.tow.data import TOWRepository

repo = TOWRepository()
res = parse_unit(WhfbAppClient().unit_entry("<slug>"))
```

`res.unit` gives the equipment, the special rules and the options;
`res.warnings` gives what the importer dropped or could not read. Compare the
equipment against `repo.weapons` / `repo.armoury` by **name**, and the rules
against `repo.rules`. The client needs `ATTRIBUTION_EMAIL` in the environment.

`parse_unit` raising is the answer, not a failure to work around:
`UnsupportedUnit` for a troop type the schema lacks (#10 for Character), and a
`ValidationError` on a non-integer characteristic (#145) or a mount's missing
cost (#144). If the unit is blocked that way, report it and stop -- do not
hand-write the datasheet.

## Import

Branch `feature/<slug>` off `dev`, then:

```sh
uv run python scripts/import_whfb_app.py unit <slug> --army <army-slug>
uv run python scripts/import_whfb_app.py weapon <weapon-slug>   # each missing one
uv run python scripts/import_whfb_app.py armour <armour-slug>
```

**Every equipment name must resolve.** Coverage is a hard error, not a note:
`test_unit_equipment_resolves` parametrises per file and fails the suite on a
dangling name. Missing weapons usually exist upstream at the obvious slug
(`weapons-of-war/sword-of-hoeth`); one that does not is a real blocker worth
reporting (a war machine's profile, say -- #3).

Read every importer warning. A dropped or misread option is data loss: #33 for
prose option lines, #5 for either/or groups.

## Then judge each rule with no entry

For each, read the printed text -- `WhfbAppClient().rule_entry(slug)["fields"]["bodyIndex"]`
is the plain prose -- and decide.

**If it folds into something the engine models, author it.** Import the entry,
then hand-author `effects:`. Read `src/avelorn/tow/schema/rule.py` for the
vocabulary first. Templates in `data/tow/rules/`:

| shape | template |
| --- | --- |
| natural-6 To Wound modifies a quantity | `armour-bane.yaml` |
| gated characteristic modifier | `elven-reflexes.yaml` |
| re-roll an attack roll | `ithilmar-weapons.yaml`, `gromril-armour.yaml` |
| re-roll a panic test | `valour-of-ages.yaml`, `veteran.yaml` |
| force a Break-test outcome | `stubborn.yaml` |
| confer another rule by name | `arrows-of-isha.yaml` |

Where the effect leaves part of the printed rule out, say so in `notes:` --
the seam surfaces it to the user (`gromril-weapons.yaml`, `stubborn.yaml`).

**Comment only what the data cannot say**: a modelling decision (why this gate
and not another) or a deliberate omission. The reader has the printed paragraph
above and the YAML below, so never paraphrase the effect, and never restate
schema vocabulary -- that belongs in the schema's own docstrings. Most rules
need no comment at all (`dragon-armour.yaml`, `press-of-battle.yaml`); where one
earns its place it is a line or three (`parry.yaml`, `killing-blow.yaml`).

**If it cannot fold, do not create a file at all.** No entry means the rule
rides along printed and reports `special rule not factored`, which is the
honest state. A file with `notes:` and no `effects:` produces the same warning
and only looks authored. `data/tow/rules/killing-blow.yaml` is the one
legitimate effect-less entry: real text the vocabulary cannot express.

Modelled: the attack dice walk (to-hit, to-wound, armour and ward saves),
casualty distributions, panic tests, break tests, charges with Stand & Shoot,
Initiative order, fighting ranks and rank bonus, combat result.

Not modelled, so the rule gets no file: terrain, deployment and reserves,
formations (#28), challenges, psychology such as Fear, the magic phase and
casting rolls, multi-unit combats, and **granting a ward save -- no quantity,
seam or unit-level target exists for one (#131)**. Denying a save has no word
either, and no gate reads the target's troop type, which is why Killing Blow
and Cleaving Blow cannot be expressed even approximately.

## Prove it works

Tests are not enough. Field the unit through `TOWGame.load_data()` and:

1. Fight it against another unit, shoot at it, and run a charge with a
   Stand & Shoot reaction plus the break test.
2. **A/B every effect you authored** -- strip the rule with
   `unit.model_copy(update={"special_rules": [...]})`, resolve again, and show
   the number moving. An effect that changes nothing was not authored, it was
   typed.
3. `make lint` clean and `make test` passing. Paste both.

Add a test only for an effect you authored, next to its seam's existing tests
(`tests/tow/phases/test_morale.py` has the panic-re-roll precedent). Do not add
a test asserting a rule stays unmodelled -- it would need rewriting the day
someone models it.

## Commit and open the PR

Plain, factual commit messages; do not imitate a repo PR-title voice.

The PR description carries **only a list of what is unmodelled and why**, naming
the blocking issue where one exists. No change summary, no test plan, no list of
what you did. Cite: #3 war machines, #5 exclusive options, #10 Character troop
type, #28 formations, #33 option prose, #34 combined profiles, #46 champion
profiles, #131 ward saves, #144 mount pricing, #145 non-integer characteristics.

If something is genuinely blocking and no issue covers it, say so in your report
rather than filing one yourself.

## Report

The PR URL; which rules you authored effects for and which you left without
files, with the reason for each; the before/after numbers proving each authored
effect fires; and anything that surprised you.
