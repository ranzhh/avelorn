"""The coverage gate: every gap between the corpus and the engine is acknowledged.

A gap is what the corpus prints and the engine never reads. Each one needs an
entry in ``data/tow/unmodelled.yaml`` saying why it stays open, and an entry no
gap needs any more is stale. `avelorn coverage` prints the same report.
"""

import pytest
import yaml

from avelorn.core.registry import Registry
from avelorn.tow.coverage import coverage, rule_gap
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.ledger import GapKind
from avelorn.tow.schema.rule import AmountParameter, Rule

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


def test_every_printed_rule_has_an_entry() -> None:
    """A rule the corpus prints is imported as text, never ledgered as missing."""
    missing = [gap.subject for gap in REPORT.gaps if gap.kind is GapKind.RULE_WITHOUT_ENTRY]
    assert not missing, "import with scripts/import_whfb_app.py rule <slug>:\n" + "\n".join(
        missing
    )


@pytest.mark.parametrize(
    ("printed", "gap"),
    [
        ("Armour Bane (1)", None),
        ("Armour Bane (+1)", GapKind.PARAMETER_UNBOUND),
        ("Armour Bane", GapKind.PARAMETER_UNBOUND),
        ("armour-bane", GapKind.PARAMETER_UNBOUND),
    ],
)
def test_a_parameter_that_does_not_bind_is_its_own_gap(printed: str, gap: GapKind | None) -> None:
    """Against the Armour Bane (X) entry, only a printed number binds."""
    assert rule_gap(printed, REPO.rules) is gap


TEXT_ONLY = Registry(
    [
        Rule(id="fear", name="Fear", paragraphs=["…"]),
        Rule(id="fly", name="Fly (X)", parameter=AmountParameter(kind="amount"), paragraphs=["…"]),
        Rule(
            id="extra-attacks",
            name="Extra Attacks (+X)",
            parameter=AmountParameter(kind="amount", dice=True),
            paragraphs=["…"],
        ),
    ],
    kind="rule",
)


@pytest.mark.parametrize(
    ("printed", "gap"),
    [
        ("Fear", GapKind.RULE_WITHOUT_EFFECTS),
        ("Fly (9)", GapKind.RULE_WITHOUT_EFFECTS),
        ("Extra Attacks (+1)", GapKind.RULE_WITHOUT_EFFECTS),
        ("Extra Attacks (-1)", GapKind.PARAMETER_UNBOUND),
        ("Ambushers", GapKind.RULE_WITHOUT_ENTRY),
    ],
)
def test_an_entry_without_effects_is_its_own_gap(printed: str, gap: GapKind) -> None:
    """A text-only entry binds but folds nothing; a sign against the template does not bind."""
    assert rule_gap(printed, TEXT_ONLY) is gap
