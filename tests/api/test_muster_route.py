"""Costing one block of an army list, over the wire."""

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
        The test client, its repository dependency pinned to one instance.
    """
    app.dependency_overrides[corpus] = lambda: REPO
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_a_block_costs_its_models(client: TestClient) -> None:
    """Ten Elven Spearmen at 8 points each, nothing bought."""
    body = client.post("/muster", json={"unit": "elven-spearmen", "size": 10}).json()
    assert body["points"] == 80
    assert body["name"] == "Elven Spearmen"


def test_a_block_costs_the_options_it_buys(client: TestClient) -> None:
    """A flat option once, a per-model option once per model."""
    body = client.post(
        "/muster",
        json={"unit": "elven-spearmen", "size": 10, "options": ["Shieldwall", "Veteran"]},
    ).json()
    assert body["points"] == 80 + 10 + 10


def test_a_block_carries_the_loadout_its_options_fold_in(client: TestClient) -> None:
    """Ellyrian Reavers swap the spear for the shortbow, and the block says so."""
    body = client.post(
        "/muster",
        json={"unit": "ellyrian-reavers", "size": 5, "options": ["Shortbows"]},
    ).json()
    assert "Shortbow" in body["equipment"]
    assert "Cavalry Spear" not in body["equipment"]


def test_a_block_says_what_it_can_fight_with(client: TestClient) -> None:
    """The weapons a block could wield, narrowed out of everything it carries."""
    body = client.post("/muster", json={"unit": "white-lions-of-chrace", "size": 20}).json()
    assert body["weapons"] == ["Hand Weapon", "Chracian Great Blade"]
    assert "Heavy Armour" in body["equipment"] and "Heavy Armour" not in body["weapons"]


def test_a_block_resolves_its_rules_the_way_a_datasheet_does(client: TestClient) -> None:
    """A block's rules address their entries, so a caller links them the same way."""
    body = client.post("/muster", json={"unit": "elven-spearmen", "size": 5}).json()
    resolved = {rule["name"]: rule["slug"] for rule in body["special_rules"]}
    assert resolved["Valour of Ages"] == "valour-of-ages"


def test_a_size_the_datasheet_forbids_is_refused_with_the_reason(client: TestClient) -> None:
    """Below the printed minimum is not a list to cost, and the message says why."""
    response = client.post("/muster", json={"unit": "elven-spearmen", "size": 2})
    assert response.status_code == 422
    assert response.json() == {"detail": "size 2 is below the unit's minimum 5"}


def test_an_option_the_datasheet_does_not_offer_is_refused(client: TestClient) -> None:
    """A name no option carries is refused rather than silently dropped."""
    response = client.post(
        "/muster", json={"unit": "elven-spearmen", "size": 5, "options": ["Great Weapon"]}
    )
    assert response.status_code == 422
    assert "Great Weapon" in response.json()["detail"]


def test_an_unknown_datasheet_is_a_404(client: TestClient) -> None:
    """A missed slug is not found, and says which slug was missed."""
    response = client.post("/muster", json={"unit": "wood-elves", "size": 5})
    assert response.status_code == 404
    assert response.json() == {"detail": "no unit 'wood-elves'"}
