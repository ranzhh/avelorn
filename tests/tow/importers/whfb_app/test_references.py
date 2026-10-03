"""Printed rule names resolve to a slug, and the X their bracket prints."""

import pytest

from avelorn.tow.data import TOWRepository
from avelorn.tow.importers.whfb_app.parse import WhfbParseError
from avelorn.tow.importers.whfb_app.references import RuleReferences
from avelorn.tow.importers.whfb_app.rules import parse_special_rule
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
        ("armour bane (1)", RuleRef(rule="armour-bane", X=1)),
        ("Requires two-hands", RuleRef(rule="requires-two-hands")),
    ],
)
def test_a_printed_name_resolves_to_its_reference(printed: str, reference: RuleRef) -> None:
    """Exact or loosely spelt names, then brackets read as the entry declares its X."""
    assert RuleReferences(REPO.rules.values()).resolve(printed, "unit some-unit") == reference


@pytest.mark.parametrize(
    ("printed", "aliases", "refusal"),
    [
        ("Extra Attacks (-1)", (), "does not print X as 'Extra Attacks \\(\\+X\\)' does"),
        ("Armour Bane (D3)", (), "X 'D3' is not an amount"),
        ("Hatred (Skaven)", (), "'Skaven' is not a selector: one of all-enemies, orcs-and"),
        ("Stubborn (1)", (), "prints an X, but stubborn declares none"),
        ("Stubborn (1)", ("Stubborn",), "prints an X, but stubborn declares none"),
        ("Armour Bane", (), "prints no X; armour-bane expects an amount"),
    ],
    ids=["sign", "kind", "selector", "extra", "extra-through-alias", "missing"],
)
def test_a_bracket_that_does_not_read_fails_the_import(
    printed: str, aliases: tuple[str, ...], refusal: str
) -> None:
    """The failure names where and what is printed and the X expected; nothing is fetched."""
    references = RuleReferences(REPO.rules.values(), _no_fetch)
    with pytest.raises(WhfbParseError, match=f"^unit some-unit: '.+': .*{refusal}"):
        references.resolve(printed, "unit some-unit", aliases)
    assert references.stubs == []


def test_a_link_target_answers_where_the_displayed_name_does_not() -> None:
    """The site files Open Order as "Open Order Formation"; an alias carries the corpus name."""
    references = RuleReferences(REPO.rules.values())
    resolved = references.resolve("Open Order Formation", "unit ships-company", ("Open Order",))
    assert resolved == RuleRef(rule="open-order")


def test_an_unknown_rule_is_fetched_as_a_text_only_stub() -> None:
    """A name no entry answers to is read from the site, and kept for the import to write."""
    references = RuleReferences(
        REPO.rules.values(),
        lambda slug: Rule(id=slug, name="Look-out Gnoblar", paragraphs=["…"]),
    )
    for _ in range(2):
        reference = references.resolve("Look-out Gnoblar", "unit maneaters")
        assert reference == RuleRef(rule="look-out-gnoblar")
    assert [stub.id for stub in references.stubs] == ["look-out-gnoblar"]


def test_an_unknown_rule_printing_an_x_is_stubbed_with_its_x_as_printed() -> None:
    """The stub declares a printed X, so the bracket binds and displays before it is modelled."""

    def page(slug: str) -> Rule:
        text = {"nodeType": "text", "value": "Regenerates."}
        body = {"content": [{"nodeType": "paragraph", "content": [text]}]}
        entry = {"fields": {"slug": slug, "name": "Regeneration (X+)", "body": body}}
        return parse_special_rule(entry).rule

    references = RuleReferences(REPO.rules.values(), page)
    assert references.resolve("Regeneration (5+)", "unit some-unit") == RuleRef(
        rule="regeneration", X=5
    )
    assert [stub.bound(5).name for stub in references.stubs] == ["Regeneration (5+)"]


def test_an_unknown_rule_without_the_site_fails_the_import() -> None:
    """With nothing to fetch it from, the import names the rule to import first."""
    with pytest.raises(WhfbParseError, match="no rule entry; import rule look-out-gnoblar"):
        RuleReferences(REPO.rules.values()).resolve("Look-out Gnoblar", "unit maneaters")


def test_a_fetched_page_the_corpus_already_holds_fails_the_import() -> None:
    """A stub never stands in for an entry the corpus holds, so no hand-written file is lost."""
    references = RuleReferences(
        REPO.rules.values(),
        lambda slug: Rule(id="stubborn", name="Stubborn", paragraphs=["…"]),
    )
    with pytest.raises(WhfbParseError, match="files it as stubborn, held as 'Stubborn'"):
        references.resolve("Stubbornness", "unit some-unit")
    assert references.stubs == []


def _no_fetch(slug: str) -> Rule:
    raise AssertionError(f"fetched {slug}")
