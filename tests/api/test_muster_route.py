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
    assert body["weapons"] == [
        {"name": "Hand Weapon", "slug": "hand-weapon", "fights": True, "shoots": False},
        {
            "name": "Chracian Great Blade",
            "slug": "chracian-great-blade",
            "fights": True,
            "shoots": False,
        },
    ]
    assert "Heavy Armour" in body["equipment"]


def test_a_weapon_that_cannot_fight_says_so(client: TestClient) -> None:
    """Archers carry a Longbow, which has no Combat profile to fight with."""
    body = client.post("/muster", json={"unit": "elven-archers", "size": 10}).json()
    assert {
        "name": "Longbow",
        "slug": "longbow",
        "fights": False,
        "shoots": True,
    } in body["weapons"]


def test_a_block_resolves_its_rules_the_way_a_datasheet_does(client: TestClient) -> None:
    """A block's rules address their entries, so a caller links them the same way."""
    body = client.post("/muster", json={"unit": "elven-spearmen", "size": 5}).json()
    resolved = {rule["name"]: rule["slug"] for rule in body["special_rules"]}
    assert resolved["Valour of Ages"] == "valour-of-ages"


def test_a_block_says_the_rectangle_it_occupies(client: TestClient) -> None:
    """Ten spearmen form up five wide on 25mm bases, so they stand on 125mm by 50mm."""
    body = client.post("/muster", json={"unit": "elven-spearmen", "size": 10}).json()
    assert body["footprint"] == {"files": 5, "ranks": 2, "width_mm": 125, "depth_mm": 50}


def test_a_rear_rank_standing_short_still_occupies_its_rank(client: TestClient) -> None:
    """Twenty-one Dwarfs four wide leave one model in a sixth rank, and it takes a rank's depth."""
    body = client.post("/muster", json={"unit": "dwarf-warriors", "size": 21}).json()
    assert body["footprint"]["ranks"] == 6
    assert body["footprint"]["depth_mm"] == 150


def test_a_cavalry_block_stands_on_its_own_base(client: TestClient) -> None:
    """A deeper base makes a deeper rectangle at the same model count."""
    reavers = client.post("/muster", json={"unit": "ellyrian-reavers", "size": 5}).json()
    assert reavers["footprint"] == {"files": 5, "ranks": 1, "width_mm": 150, "depth_mm": 60}


def test_a_block_re_forms_to_the_width_asked_for(client: TestClient) -> None:
    """Twenty spearmen ten wide are two ranks deep instead of four."""
    body = client.post(
        "/muster", json={"unit": "elven-spearmen", "size": 20, "frontage": 10}
    ).json()
    assert body["footprint"] == {"files": 10, "ranks": 2, "width_mm": 250, "depth_mm": 50}


def test_re_forming_costs_nothing(client: TestClient) -> None:
    """Standing wider is a formation, not a purchase."""
    wide = client.post("/muster", json={"unit": "elven-spearmen", "size": 20, "frontage": 10})
    deep = client.post("/muster", json={"unit": "elven-spearmen", "size": 20, "frontage": 4})
    assert wide.json()["points"] == deep.json()["points"]


def test_a_frontage_wider_than_the_block_is_the_block(client: TestClient) -> None:
    """A caller dragging an edge past the unit's width gets the truth back."""
    body = client.post(
        "/muster", json={"unit": "elven-spearmen", "size": 20, "frontage": 40}
    ).json()
    assert body["footprint"]["files"] == 20
    assert body["footprint"]["ranks"] == 1


def test_a_short_rear_rank_still_takes_a_rank_at_a_chosen_frontage(client: TestClient) -> None:
    """Twenty spearmen seven wide leave six in a third rank, which takes its depth."""
    body = client.post(
        "/muster", json={"unit": "elven-spearmen", "size": 20, "frontage": 7}
    ).json()
    assert body["footprint"]["ranks"] == 3
    assert body["footprint"]["depth_mm"] == 75


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
