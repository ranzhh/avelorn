"""The program a resolution ran on, served for the body that resolved it."""

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


def served(client: TestClient, route: str, body: dict) -> dict:
    """Post a body, failing loudly on a refusal.

    Returns:
        The response body.
    """
    response = client.post(route, json=body)
    assert response.status_code == 200, response.json()
    return response.json()


def lost(program: dict, path: str, size: int) -> dict[int, float]:
    """The models a side has lost by a remove-casualties step, read off the program.

    Returns:
        Each count lost, with its probability.
    """
    (step,) = (node for node in program["nodes"] if node["path"] == path)
    (standing,) = (each for each in step["edge"]["readings"] if each["label"] == "models")
    return {size - outcome["value"]: outcome["p"] for outcome in standing["outcomes"]}


def listed(casualties: list[float]) -> dict[int, float]:
    """A report's casualty list, each count it can lose with its probability.

    Returns:
        The counts with any chance.
    """
    return {count: p for count, p in enumerate(casualties) if p}


def test_the_volley_graph_is_the_volley_reported(client: TestClient) -> None:
    """A shooter that moved needs a worse roll, in the program as in the report."""
    body = {
        "shooter": {"unit": "elven-archers", "size": 10},
        "target": {"unit": "elven-spearmen", "size": 20},
        "distance": 20,
        "moved": True,
    }
    report = served(client, "/volley", body)
    program = served(client, "/graph/volley", body)

    assert program["program"] == "volley"
    assert lost(program, "volley/remove-casualties", 20) == listed(report["casualties"])


@pytest.mark.parametrize(
    ("resolved", "drawn", "body"),
    [
        (
            "/fight",
            "/graph/fight",
            {
                "a": {"unit": "elven-archers", "size": 10, "weapon": "Longbow"},
                "b": {"unit": "dwarf-warriors", "size": 10},
            },
        ),
        (
            "/volley",
            "/graph/volley",
            {
                "shooter": {"unit": "dwarf-warriors", "size": 10},
                "target": {"unit": "elven-spearmen", "size": 20},
                "distance": 12,
            },
        ),
    ],
)
def test_a_refused_deployment_is_refused_the_same_way(
    client: TestClient, resolved: str, drawn: str, body: dict
) -> None:
    """The program is drawn only for a body the resolution would take."""
    refused = client.post(resolved, json=body)
    assert refused.status_code == 422
    drawing = client.post(drawn, json=body)
    assert (drawing.status_code, drawing.json()) == (422, refused.json())
