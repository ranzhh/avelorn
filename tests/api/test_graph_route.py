"""Graph route."""

from fastapi.testclient import TestClient

from avelorn.api.app import app


def test_the_volley_graph_serves_the_volley_program() -> None:
    """Serve the YAML volley."""
    body = TestClient(app).get("/graph/volley")

    assert body.status_code == 200
    program = body.json()
    assert program["program"] == "volley"
    assert [node["path"] for node in program["nodes"]] == [
        "volley/check-range",
        "volley/how-many-shots",
        "volley/attack/roll-to-hit",
        "volley/attack/roll-to-wound",
        "volley/attack/make-armour-saves",
        "volley/attack/ward-saves",
        "volley/remove-casualties",
        "volley/heavy-casualties",
        "volley/make-panic-tests",
        "volley/fall-back-or-flee",
    ]
    assert program["blocks"] == [
        {
            "path": "volley/attack",
            "kind": "repeat",
            "times": "volley/how-many-shots",
            "collapsed": False,
        }
    ]
    assert program["nodes"][1]["edge"]["readings"] == [
        {"label": "shots", "outcomes": [{"value": 5, "p": 1.0}]}
    ]
    assert program["nodes"][2]["target"] == {
        "label": "needed",
        "outcomes": [{"value": "3+", "p": 1.0}],
    }
    assert program["rules"] == []
