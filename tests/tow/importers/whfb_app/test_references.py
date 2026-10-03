"""Printed rule names resolve to a slug, and the X their bracket prints."""

import pytest

from avelorn.tow.data import TOWRepository
from avelorn.tow.importers.whfb_app.parse import WhfbParseError
from avelorn.tow.importers.whfb_app.references import RuleReferences
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import Rule

REPO = TOWRepository()


@pytest.mark.parametrize(
    ("printed", "reference"),
    [
        ("Stubborn", RuleRef(rule="stubborn")),
        ("Fight in Extra Rank", RuleRef(rule="fight-in-extra-rank")),
        ("Armour Bane (1)", RuleRef(rule="armour-bane", X=1)),
        ("Extra Attacks (+1)", RuleRef(rule="extra-attacks", X=1)),
        ("Magic Resistance (-1)", RuleRef(rule="magic-resistance", X=1)),
        ("Impact Hits (D3)", RuleRef(rule="impact-hits", X="D3")),
        ("Hatred (Orcs & Goblins)", RuleRef(rule="hatred", X="orcs-and-goblins")),
    ],
)
def test_a_printed_name_resolves_to_its_reference(printed: str, reference: RuleRef) -> None:
    """Exact or loosely spelt names, then brackets read as the entry declares its X."""
    assert RuleReferences(REPO.rules.values()).resolve(printed, "unit some-unit") == reference


@pytest.mark.parametrize(
    ("printed", "refusal"),
    [
        ("Extra Attacks (-1)", "does not print X as 'Extra Attacks \\(\\+X\\)' does"),
        ("Armour Bane (D3)", "X 'D3' is not an amount"),
        ("Hatred (Skaven)", "'Skaven' is not a selector: one of all-enemies, orcs-and-goblins"),
        ("Stubborn (1)", "prints an X, but stubborn declares none"),
    ],
)
def test_a_bracket_that_does_not_read_fails_the_import(printed: str, refusal: str) -> None:
    """The failure names where the name is printed, the name, and the X expected."""
    references = RuleReferences(REPO.rules.values())
    with pytest.raises(WhfbParseError, match=f"^unit some-unit: '.+': .*{refusal}"):
        references.resolve(printed, "unit some-unit")


def test_a_link_target_answers_where_the_displayed_name_does_not() -> None:
    """Ship's Company displays "Open Order Formation", linking the Open Order entry."""
    references = RuleReferences(REPO.rules.values())
    resolved = references.resolve("Open Order Formation", "unit ships-company", ("Open Order",))
    assert resolved == RuleRef(rule="open-order")


def test_an_unknown_rule_is_fetched_as_a_text_only_stub() -> None:
    """A name no entry answers to is read from the site, and kept for the import to write."""
    references = RuleReferences(
        REPO.rules.values(),
        lambda slug: Rule(id=slug, name="Poisoned Attacks", paragraphs=["…"]),
    )
    for _ in range(2):
        reference = references.resolve("Poisoned Attacks", "unit maneaters")
        assert reference == RuleRef(rule="poisoned-attacks")
    assert [stub.id for stub in references.stubs] == ["poisoned-attacks"]


def test_an_unknown_rule_without_the_site_fails_the_import() -> None:
    """With nothing to fetch it from, the import names the rule to import first."""
    with pytest.raises(WhfbParseError, match="no rule entry; import rule poisoned-attacks"):
        RuleReferences(REPO.rules.values()).resolve("Poisoned Attacks", "unit maneaters")
