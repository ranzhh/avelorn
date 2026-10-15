"""A volley drawn in two lanes, served for the body /volley resolves."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from avelorn.api.app import app, corpus
from avelorn.tow.data import TOWRepository

REPO = TOWRepository()

ARCHERS_SHOOT_SPEARMEN = {
    "shooter": {"unit": "elven-archers", "size": 10},
    "target": {"unit": "elven-spearmen", "size": 20},
    "distance": 12,
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client serving the committed corpus.

    Yields:
        The test client, its repository dependency pinned to one instance.
    """
    app.dependency_overrides[corpus] = lambda: REPO
    yield TestClient(app)
    app.dependency_overrides.clear()


def served(client: TestClient, route: str, body: dict) -> dict:
    """Post a body, failing loudly on a refusal.

    Returns:
        The response body.
    """
    response = client.post(route, json=body)
    assert response.status_code == 200, response.json()
    return response.json()


def test_the_drawn_volley_is_the_volley_reported(client: TestClient) -> None:
    """A shooter that moved needs a worse roll, in the drawing as in the report."""
    body = {**ARCHERS_SHOOT_SPEARMEN, "moved": True}
    report = served(client, "/volley", body)
    lanes = served(client, "/graph/volley", body)

    assert (lanes["volley"]["needed"]["hit"], lanes["battlefield"]["moved"]) == ("4+", True)
    assert lanes["volley"]["casualties"]["distribution"] == pytest.approx(report["casualties"])
    assert lanes["units"]["attacker"]["held"] == [report["shooter"]["weapon"]]


@pytest.mark.parametrize(("inches", "band"), [(12, "short"), (25, "long")])
def test_the_battlefield_names_the_range_band(client: TestClient, inches: int, band: str) -> None:
    """A Longbow's range is 30in: within half of it is short range, beyond it long range."""
    lanes = served(client, "/graph/volley", {**ARCHERS_SHOOT_SPEARMEN, "distance": inches})

    assert lanes["battlefield"] == {"distance": inches, "band": band, "moved": False}


def test_heavy_casualties_force_the_panic_test(client: TestClient) -> None:
    """Twenty Spearmen test when they lose more than a quarter of their number: six or more.

    Every test is passed, or failed with a Fall Back in Good Order or a Flee.
    """
    lanes = served(client, "/graph/volley", ARCHERS_SHOOT_SPEARMEN)
    panic = lanes["panic"]

    assert panic["taken"] == pytest.approx(sum(lanes["volley"]["casualties"]["distribution"][6:]))
    assert panic["passed"] + panic["falls_back_in_good_order"] + panic["flees"] == pytest.approx(
        panic["taken"]
    )
