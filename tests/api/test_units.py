"""The HTTP surface, driven in process against the real corpus under data/."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from avelorn.api.app import app, corpus
from avelorn.tow.coverage import Gap
from avelorn.tow.data import TOWRepository
from avelorn.tow.views import RuleSummary

REPO = TOWRepository()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client serving the committed corpus.

    Yields:
        The test client, its repository dependency pinned to one instance so a
        test never depends on what an earlier one warmed.
    """
    app.dependency_overrides[corpus] = lambda: REPO
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_listing_covers_the_corpus(client: TestClient) -> None:
    """Every datasheet is listed, ordered by slug."""
    body = client.get("/units").json()
    assert [unit["id"] for unit in body] == sorted(REPO.units)


def test_the_listing_carries_what_a_list_needs_and_no_more(client: TestClient) -> None:
    """A summary says what a unit costs and how it is fielded, not what it is made of."""
    archers = next(unit for unit in client.get("/units").json() if unit["id"] == "elven-archers")
    assert archers == {
        "id": "elven-archers",
        "name": "Elven Archers",
        "points": 9,
        "unit_size": {"min": 5, "max": None},
        "troop_type": "Regular Infantry",
        "armies": ["high-elf-realms"],
    }


def test_a_listing_says_which_armies_field_a_unit(client: TestClient) -> None:
    """A browser groups by army, so the summary carries the armies filing it."""
    listed = {unit["id"]: unit["armies"] for unit in client.get("/units").json()}
    assert listed["elven-archers"] == ["high-elf-realms"]
    assert listed["dwarf-warriors"] == ["dwarfen-mountain-holds"]
    assert all(armies for armies in listed.values())


def test_a_datasheet_is_served_whole(client: TestClient) -> None:
    """The detail route carries the parts the listing leaves out."""
    body = client.get("/units/white-lions-of-chrace").json()
    assert [profile["name"] for profile in body["profiles"]] == ["White Lion", "Guardian"]
    assert {
        "name": "Chracian Great Blade",
        "kind": "weapon",
        "slug": "chracian-great-blade",
    } in body["equipment"]
    assert {"name": "Heavy Armour", "kind": "armour", "slug": "heavy-armour"} in body["equipment"]
    assert {"name": "Lion Cloak", "kind": "rule", "slug": "lion-cloak"} in body["special_rules"]


def test_a_printed_rule_carries_the_entry_it_resolves_to(client: TestClient) -> None:
    """A caller can address the rule without deriving a slug from the name."""
    body = client.get("/units/white-lions-of-chrace").json()
    resolved = {r["name"]: r["slug"] for r in body["special_rules"]}
    assert resolved["Lion Cloak"] == "lion-cloak"
    assert client.get("/rules/lion-cloak").status_code == 200


def test_a_text_only_rule_links_to_its_entry(client: TestClient) -> None:
    """A rule the engine does not apply still links to the text it holds."""
    body = client.get("/units/dwarf-warriors").json()
    resolved = {r["name"]: r["slug"] for r in body["special_rules"]}
    assert resolved["Close Order"] == "close-order"


def test_a_parameterised_rule_resolves_to_the_template_it_is_filed_under(
    client: TestClient,
) -> None:
    """The Merwyrm prints Impact Hits (D3); the entry is filed as Impact Hits (X)."""
    body = client.get("/units/merwyrm").json()
    resolved = {r["name"]: r["slug"] for r in body["special_rules"]}
    assert resolved["Impact Hits (D3)"] == "impact-hits"
    assert client.get("/rules/impact-hits").json()["name"] == "Impact Hits (X)"


def test_an_option_names_the_rules_it_swaps_as_the_datasheet_prints_them(
    client: TestClient,
) -> None:
    """Ship's Company may trade Open Order for Skirmish Formation."""
    body = client.get("/units/ships-company").json()
    swap = next(o for o in body["options"] if o["name"] == "Skirmish Formation")
    assert swap["adds_rules"] == [
        {"name": "Skirmish Formation", "kind": "rule", "slug": "skirmish-formation"}
    ]
    assert swap["removes_rules"] == [{"name": "Open Order", "kind": "rule", "slug": "open-order"}]


def test_a_datasheet_carries_its_resolved_troop_type(client: TestClient) -> None:
    """The repository attaches how a unit ranks up, and the response keeps it."""
    body = client.get("/units/elven-spearmen").json()
    assert body["troop_type_profile"]["name"] == "Regular Infantry"


def test_an_unknown_slug_is_a_404(client: TestClient) -> None:
    """A missed slug is not found, and says which slug was missed."""
    response = client.get("/units/wood-elves")
    assert response.status_code == 404
    assert response.json() == {"detail": "no unit 'wood-elves'"}


def test_rules_are_listed_through_the_shared_summary(client: TestClient) -> None:
    """The rule listing carries the shared view's fields, one entry each."""
    body = client.get("/rules").json()
    assert [r["id"] for r in body] == sorted(REPO.rules)
    assert set(body[0]) == set(RuleSummary.model_fields)


def test_the_coverage_report_names_each_gap_where_it_occurs_and_why(client: TestClient) -> None:
    """The report is the per-action "not factored" notes, totalled and explained."""
    gap = client.get("/coverage").json()["gaps"][0]
    assert set(gap) == set(Gap.model_fields)
    assert set(gap["sites"][0]) == {"entry", "id"}
    assert gap["reason"]


def test_a_rule_is_served_whole(client: TestClient) -> None:
    """The detail route is the schema type, effects and notes included."""
    body = client.get("/rules/stubborn").json()
    # Served with its nulls, as every response model is; the CLI drops them for
    # readability, which is rendering rather than a difference in what is carried.
    assert body["effects"] == [{"when": None, "forces": {"break": "fall-back-in-good-order"}}]
    assert body["notes"]


def test_a_rule_is_served_with_its_graph(client: TestClient) -> None:
    """Armour Bane's effect is served with the step it lands at."""
    body = client.get("/rules/armour-bane").json()
    assert [clause["effect"]["at"] for clause in body["graph"]["clauses"]] == [
        {"step": "make-armour-saves", "by": "the-enemy", "in": None, "not_in": None}
    ]


def test_an_unknown_rule_slug_is_a_404(client: TestClient) -> None:
    """A slug no entry carries has nothing to read."""
    response = client.get("/rules/unprinted-rule")
    assert response.status_code == 404
    assert response.json() == {"detail": "no rule entry 'unprinted-rule'"}
