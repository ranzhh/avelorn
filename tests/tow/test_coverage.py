"""The coverage gate: every gap between the corpus and the engine is acknowledged.

A gap is what the corpus prints and the engine never reads. Each one needs an
entry in ``data/tow/unmodelled.yaml`` saying why it stays open, and an entry no
gap needs any more is stale. `avelorn coverage` prints the same report.
"""

import yaml

from avelorn.tow.coverage import attached, coverage
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.effect import Address
from avelorn.tow.schema.ledger import GapKind

REPO = TOWRepository()
REPORT = coverage(REPO)


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


def test_an_effect_attaches_where_a_program_registers_its_step() -> None:
    """Roll To Hit attaches through the volley; narrowed to combat, no program registers it."""
    shooting = Address.model_validate({"step": "roll-to-hit", "by": "this-model"})
    combat = Address.model_validate({"step": "roll-to-hit", "by": "this-model", "in": "combat"})
    assert attached(shooting)
    assert not attached(combat)


def test_an_unattached_effect_is_one_gap_per_rule_and_step() -> None:
    """Veteran's re-roll attaches at the Panic test, and waits at the rally test."""
    unattached = {gap.subject for gap in REPORT.gaps if gap.kind is GapKind.UNATTACHED_EFFECT}
    assert "veteran/rally-fleeing-units" in unattached
    assert "veteran/make-panic-tests" not in unattached
