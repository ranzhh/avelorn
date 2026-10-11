"""A round of combat drawn in two lanes, served for the body /fight resolves."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from avelorn.api.app import app, corpus
from avelorn.tow.data import TOWRepository

REPO = TOWRepository()

PRINCES_CHARGE_DWARFS = {
    "a": {"unit": "dragon-princes", "size": 5, "options": ["drakemaster"]},
    "b": {"unit": "dwarf-warriors", "size": 10, "options": ["veteran"]},
    "charge": {"side": "a", "full_inches": 7, "arc": "front"},
}
SPEARMEN_CHARGE_ARCHERS = {
    "a": {"unit": "elven-archers", "size": 10, "frontage": 5},
    "b": {"unit": "elven-spearmen", "size": 20, "frontage": 5},
    "charge": {"side": "b", "full_inches": 8, "arc": "front", "reaction": "stand-and-shoot"},
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


@pytest.mark.parametrize("body", [PRINCES_CHARGE_DWARFS, SPEARMEN_CHARGE_ARCHERS])
def test_the_lanes_are_the_round_the_fight_reports(client: TestClient, body: dict) -> None:
    """The charger takes the upper lane, and the outcomes are the ones /fight reports."""
    report = served(client, "/fight", body)
    lanes = served(client, "/graph/fight", body)

    charger = body["charge"]["side"]
    seats = {"attacker": charger, "target": "b" if charger == "a" else "a"}
    for seat, side in seats.items():
        assert lanes["units"][seat]["unit"] == report[side]["unit"]
        broke = lanes["breaks"][seat]
        assert [broke["give_ground"], broke["fall_back_in_good_order"], broke["break"]] == [
            pytest.approx(report[side][outcome])
            for outcome in ("gives_ground", "falls_back", "breaks")
        ]
    result = lanes["result"]
    assert [result["attacker_wins"], result["draw"], result["target_wins"]] == [
        pytest.approx(report[f"p_{charger}_wins"]),
        pytest.approx(report["p_draw"]),
        pytest.approx(report[f"p_{seats['target']}_wins"]),
    ]


def test_a_stand_and_shoot_thins_the_charger(client: TestClient) -> None:
    """Ten Archers five wide stand and shoot at twenty Spearmen charging them.

    The front rank's five shoot; a Stand & Shoot never Volley Fires. BS4 hits
    on 3+, 4+ for Standing and Shooting; the Longbow's S3 wounds T3 on 4+; the
    Spearmen's light armour and shield save on 5+, on 6+ against a natural 6
    To Wound for the Longbow's Armour Bane (1). Each shot goes unsaved
    1/2 x (2/6 x 4/6 + 1/6 x 5/6) = 13/72 of the time. Both rules are the
    Archers', who fight from the target's lane.
    """
    lanes = served(client, "/graph/fight", SPEARMEN_CHARGE_ARCHERS)

    assert lanes["units"]["attacker"]["unit"] == "elven-spearmen"
    assert lanes["reaction"] == {
        "chosen": "stand-and-shoot",
        "offered": {"hold": True, "stand_and_shoot": True, "flee": False},
    }
    volley = lanes["volley"]
    assert (volley["shots"], volley["needed"]) == (
        5,
        {"hit": "4+", "wound": "4+", "save": "5+ or 6+", "ward": "-"},
    )
    assert [(each["after"], each["models"]) for each in lanes["standing"]["attacker"][:2]] == [
        (None, 20),
        ("volley", pytest.approx(20 - 5 * 13 / 72)),
    ]
    shooting = {rule["name"]: rule["side"] for rule in volley["rules"] if rule["applied"]}
    assert shooting == {"Armour Bane (1)": "target", "Standing and Shooting": "target"}
