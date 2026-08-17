"""The HTTP surface, driven in process against the real corpus under data/."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from avelorn.api.app import app, corpus
from avelorn.tow.data import TOWRepository

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
    }


def test_a_datasheet_is_served_whole(client: TestClient) -> None:
    """The detail route carries the parts the listing leaves out."""
    body = client.get("/units/white-lions-of-chrace").json()
    assert [profile["name"] for profile in body["profiles"]] == ["White Lion", "Guardian"]
    assert "Chracian Great Blade" in body["equipment"]
    assert "Lion Cloak" in body["special_rules"]


def test_a_datasheet_carries_its_resolved_troop_type(client: TestClient) -> None:
    """The repository attaches how a unit ranks up, and the response keeps it."""
    body = client.get("/units/elven-spearmen").json()
    assert body["troop_type_profile"]["name"] == "Regular Infantry"


def test_an_unknown_slug_is_a_404(client: TestClient) -> None:
    """A missed slug is not found, and says which slug was missed."""
    response = client.get("/units/wood-elves")
    assert response.status_code == 404
    assert response.json() == {"detail": "no unit 'wood-elves'"}
