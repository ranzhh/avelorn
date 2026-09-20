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
        "shots",
        "choose-range",
        "roll-to-hit",
        "roll-to-wound",
        "remove-casualties",
    ]
    assert [block["kind"] for block in program["blocks"]] == ["repeat", "lanes"]
    assert program["nodes"][2]["edge"]["readings"][0]["label"] == "hits"
    assert program["rules"][0]["landings"] == [
        {"at": "volley/attack/roll-to-hit", "verdict": "applied"},
        {"at": "volley/aftermath/remove-casualties", "verdict": "honoured"},
    ]
