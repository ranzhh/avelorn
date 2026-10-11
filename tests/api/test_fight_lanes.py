"""A round of combat drawn in two lanes, served for the body /fight resolves."""

from collections.abc import Iterator
from fractions import Fraction

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


@pytest.mark.parametrize(
    ("inches", "reaches"),
    [
        pytest.param(7, Fraction(35, 36), id="needs-a-2"),
        pytest.param(11, Fraction(11, 36), id="needs-a-6"),
        pytest.param(12, Fraction(0), id="past-the-maximum"),
    ],
)
def test_the_charge_reaches_on_the_higher_of_two_dice(
    client: TestClient, inches: int, reaches: Fraction
) -> None:
    """Elven Spearmen move 5 and add the higher of two D6 to it.

    At 7in the higher die needs a 2, failing only on two 1s: 1 - (1/6)^2. At
    11in it needs a 6 on either die: 1 - (5/6)^2. 12in is past the maximum
    possible charge range of 5 + 6. Both routes report the chance.
    """
    charge = {**SPEARMEN_CHARGE_ARCHERS["charge"], "full_inches": inches}
    body = {**SPEARMEN_CHARGE_ARCHERS, "charge": charge}
    report = served(client, "/fight", body)
    lanes = served(client, "/graph/fight", body)

    assert [report["p_charge_reaches"], lanes["charge"]["reaches"]] == [float(reaches)] * 2


@pytest.mark.parametrize("body", [PRINCES_CHARGE_DWARFS, SPEARMEN_CHARGE_ARCHERS])
def test_the_lanes_are_the_round_the_fight_reports(client: TestClient, body: dict) -> None:
    """The charger takes the upper lane, and every figure is the one /fight reports."""
    report = served(client, "/fight", body)
    lanes = served(client, "/graph/fight", body)

    charger = body["charge"]["side"]
    seats = {"attacker": charger, "target": "b" if charger == "a" else "a"}
    for seat, side in seats.items():
        size = report[side]["size"]
        assert lanes["units"][seat]["unit"] == report[side]["unit"]
        standing = lanes["standing"][seat][-1]["distribution"]
        lost = report[side]["casualties"]
        assert {left: p for left, p in enumerate(standing) if p} == pytest.approx(
            {size - count: p for count, p in enumerate(lost) if p}
        )
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


def test_a_strike_lists_the_parts_that_make_it(client: TestClient) -> None:
    """Five Dragon Princes, a Drakemaster among them, charge ten Dwarf Warriors 7in into the front.

    Four wide, the Drakemaster and three Princes stand in the front rank. The
    riders strike at I5, +1 for Elven Reflexes and +3 for the charge, and the
    steeds at I4 +3; the Dwarfs at I2. A rider hits on 3+ (WS5 against WS4)
    and, with the Lance's S+2, wounds T4 on 3+ at AP -2, past the Dwarfs'
    heavy armour: 4/9 of an attack goes unsaved, of the Drakemaster's three
    and the Princes' six. A steed hits on 4+, wounds on 5+, and the Dwarf
    saves on 5+: 1/9 of each steed's attack. A Dwarf hits on 4+ and wounds
    on 4+; a Prince saves on 2+ in full plate, shield and barding, with a 6+
    ward from Dragon Armour. Every other step is empty.
    """
    lanes = served(client, "/graph/fight", PRINCES_CHARGE_DWARFS)

    struck = [
        (
            strike["label"],
            strike["side"],
            [
                (part["name"], part["models"], part["attacks"], part["unsaved"])
                for part in strike["parts"]
            ],
        )
        for strike in lanes["strikes"][:2]
    ]
    assert struck == [
        (
            "Initiative 9",
            "attacker",
            [
                ("Drakemaster", 1, 3, pytest.approx(3 * 4 / 9)),
                ("Dragon Prince", 3, 6, pytest.approx(6 * 4 / 9)),
            ],
        ),
        ("Initiative 7", "attacker", [("Barded Elven Steed", 4, 4, pytest.approx(4 / 9))]),
    ]
    dwarfs = lanes["strikes"][2:]
    assert [(strike["label"], strike["side"]) for strike in dwarfs] == [("Initiative 2", "target")]
    assert [part["name"] for part in dwarfs[0]["parts"]] == ["Veteran", "Dwarf Warrior"]
    assert dwarfs[0]["needed"] == {"hit": "4+", "wound": "4+", "save": "2+", "ward": "6+"}


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
