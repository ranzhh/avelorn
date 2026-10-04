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
        "volley/who-can-shoot",
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
    assert program["nodes"][0]["changes"] == [
        {"rule": "attacker/elven-archers/volley-fire", "text": "allow half-of-each-rear-rank"}
    ]
    assert program["nodes"][2]["edge"]["readings"] == [
        {"label": "shots", "outcomes": [{"value": 8, "p": 1.0}]}
    ]
    assert program["nodes"][3]["target"] == {
        "label": "needed",
        "outcomes": [{"value": "3+", "p": 1.0}],
    }
    assert program["nodes"][3]["printed"] == {
        "label": "printed",
        "outcomes": [{"value": "3+", "p": 1.0}],
    }
    assert [rule["id"] for rule in program["rules"]] == [
        "attacker/elven-archers/armour-bane",
        "attacker/elven-archers/close-order",
        "attacker/elven-archers/detachment",
        "attacker/elven-archers/firing-at-long-range",
        "attacker/elven-archers/moving-and-shooting",
        "attacker/elven-archers/volley-fire",
        "target/elven-spearmen/close-order",
        "target/elven-spearmen/regimental-unit",
        "target/elven-spearmen/valour-of-ages",
    ]
