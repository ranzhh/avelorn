"""The graph surface returns the evaluated example program."""

from fastapi.testclient import TestClient

from avelorn.api.app import app


def test_the_volley_graph_has_steps_blocks_readings_and_rules() -> None:
    """The endpoint serves the contract consumed by the graph frontend."""
    body = TestClient(app).get("/graph/volley")

    assert body.status_code == 200
    program = body.json()
    assert program["program"] == "volley"
    assert [node["step"] for node in program["nodes"]] == [
        "models",
        "frontage",
        "target-models",
        "distance",
        "weapon-range",
        "range",
        "shots",
        "roll-to-hit",
        "roll-to-wound",
        "remove-casualties",
        "panic-flight",
    ]
    assert [block["kind"] for block in program["blocks"]] == [
        "sequence",
        "sequence",
        "repeat",
        "sequence",
    ]
    assert [block["path"] for block in program["blocks"]] == [
        "volley/pre-volley",
        "volley/volley",
        "volley/volley/attack",
        "volley/result",
    ]
    assert program["nodes"][7]["edge"]["readings"][0]["label"] == "hits"
    assert program["rules"][0]["landings"] == [
        {"at": "volley/pre-volley/shots", "verdict": "held"},
    ]
