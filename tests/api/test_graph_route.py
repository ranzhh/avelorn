"""A drawing of a resolution, refused for the body the resolution refuses."""

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
    """A drawing is made only for a body the resolution would take."""
    refused = client.post(resolved, json=body)
    assert refused.status_code == 422
    drawing = client.post(drawn, json=body)
    assert (drawing.status_code, drawing.json()) == (422, refused.json())
