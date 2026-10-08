"""The coverage gate: every gap between the corpus and the engine is acknowledged.

A gap is what the corpus prints and the engine never reads. Each one needs an
entry in ``data/tow/unmodelled.yaml`` saying why it stays open, and an entry no
gap needs any more is stale. `avelorn coverage` prints the same report.
"""

import copy

import yaml

from avelorn.core.registry import Registry
from avelorn.tow.coverage import Entry, Site, coverage
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.ledger import GapKind
from avelorn.tow.schema.rule import Clause, RuleGraph
from avelorn.tow.schema.unit import Characteristic

REPO = TOWRepository()
REPORT = coverage(REPO)

UNATTACHED = {gap.subject for gap in REPORT.gaps if gap.kind is GapKind.UNATTACHED_EFFECT}
UNREACHED = {gap.subject for gap in REPORT.gaps if gap.kind is GapKind.UNREACHED_EFFECT}


def test_every_gap_is_acknowledged_in_the_ledger() -> None:
    """A new gap fails here until data/tow/unmodelled.yaml says why it stays open."""
    missing = [
        yaml.safe_dump(
            [{"kind": str(gap.kind), "subject": gap.subject, "reason": ""}], sort_keys=False
        )
        + "# in "
        + ", ".join(f"{site.entry} {site.id}" for site in gap.sites)
        for gap in REPORT.gaps
        if gap.reason is None
    ]
    assert not missing, "add to data/tow/unmodelled.yaml, with a reason:\n" + "\n".join(missing)


def test_every_ledger_entry_still_matches_a_gap() -> None:
    """A gap closed by modelling it fails here until its entry is deleted."""
    stale = [f"{entry.kind}: {entry.subject}" for entry in REPORT.stale]
    assert not stale, "delete from data/tow/unmodelled.yaml, nothing needs them:\n" + "\n".join(
        stale
    )


def test_a_rule_without_effects_is_one_gap_whatever_its_x() -> None:
    """Fly (9) and Fly (10) reference one text-only rule, ledgered once by its slug."""
    fly = next(gap for gap in REPORT.gaps if gap.subject == "fly")
    assert fly.kind is GapKind.RULE_WITHOUT_EFFECTS
    assert {"frostheart-phoenix", "great-eagle"} <= {site.id for site in fly.sites}


def test_an_effect_waits_for_each_sequence_it_lands_in() -> None:
    """Veteran's re-roll attaches through the volley and waits for a Panic test outside one."""
    assert "veteran/panic/make-panic-tests" in UNATTACHED
    assert "veteran/shooting/make-panic-tests" not in UNATTACHED


def test_an_effect_waits_for_the_step_that_triggers_it() -> None:
    """Valour of Ages' re-roll waits for Fled Through, while Heavy Casualties is registered."""
    assert "valour-of-ages/panic/fled-through" in UNATTACHED
    assert "valour-of-ages/panic/heavy-casualties" not in UNATTACHED


def test_an_effect_waits_for_a_step_it_reads_as_a_fact() -> None:
    """Furious Charge reads the length of a charge move no program registers yet."""
    assert "furious-charge/charge/the-charge-move" in UNATTACHED


def test_a_volley_effect_waits_for_a_side_that_carries_it_there() -> None:
    """Multiple Wounds is printed only on a combat profile, so no shooter carries it."""
    assert "multiple-wounds/shooting/remove-casualties" in UNREACHED
    assert "armour-bane/shooting/make-armour-saves" not in UNREACHED


def test_an_effect_its_step_cannot_run_is_held() -> None:
    """Martial Prowess rewritten to set Weapon Skill is held at Roll To Hit in combat.

    That step runs no set, and the Elven Spearmen alone carry the rule there.
    """
    printed = REPO.rules["martial-prowess"]
    assert printed.graph is not None
    striking = printed.graph.effects[0]
    fixed = striking.model_copy(update={"add": None, "set_": {Characteristic.WEAPON_SKILL: 5}})
    rewritten = printed.with_graph(RuleGraph(clauses=(Clause(effect=fixed),)))
    data = copy.copy(REPO)
    data.rules = Registry({**REPO.rules, rewritten.id: rewritten}.values(), kind="rule")
    data.units = Registry([REPO.units["elven-spearmen"]], kind="unit")
    report = coverage(data)
    held = {gap.subject for gap in report.gaps if gap.kind is GapKind.HELD_EFFECT}
    assert "martial-prowess/combat/roll-to-hit" in held


def test_a_rule_granted_only_by_the_graph_is_referenced_there() -> None:
    """Flaming Attacks grants Fear in the graph alone, and the Fear gap names it."""
    fear = next(gap for gap in REPORT.gaps if gap.subject == "fear")
    assert Site(entry=Entry.RULE, id="flaming-attacks") in fear.sites
