"""Resolving a round of close combat over the wire."""

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


def fight(client: TestClient, **body: object) -> dict:
    """Resolve a round, failing loudly on a refusal.

    Returns:
        The report.
    """
    response = client.post("/fight", json=body)
    assert response.status_code == 200, response.json()
    return response.json()


def test_both_sides_are_reported(client: TestClient) -> None:
    """A round names what each side fielded and what it fought with."""
    report = fight(
        client,
        a={"unit": "white-lions-of-chrace", "size": 20},
        b={"unit": "dwarf-warriors", "size": 20},
    )
    assert report["a"]["name"] == "White Lions of Chrace"
    assert report["b"]["size"] == 20


def test_the_outcome_is_a_distribution_not_an_average(client: TestClient) -> None:
    """Every casualty count carries its own probability, and they exhaust the space."""
    report = fight(
        client,
        a={"unit": "elven-spearmen", "size": 20},
        b={"unit": "elven-spearmen", "size": 20},
    )
    losses = report["b"]["casualties"]
    assert len(losses) > 1
    assert sum(losses) == pytest.approx(1.0)
    assert report["p_a_wins"] + report["p_draw"] + report["p_b_wins"] == pytest.approx(1.0)


def test_the_reported_initiative_is_the_one_the_ordering_compared(client: TestClient) -> None:
    """The blade's Strike Last is already in the figure, which is why the Lions swing second."""
    report = fight(
        client,
        a={"unit": "white-lions-of-chrace", "size": 20},
        b={"unit": "dwarf-warriors", "size": 20},
    )
    assert report["a"]["weapon"] == "Chracian Great Blade"
    # The printed profile has the Lions far quicker than a Dwarf; the weapon is
    # what puts them second, and the reported value shows it rather than the
    # datasheet's number.
    assert report["a"]["initiative"] < report["b"]["initiative"]
    assert report["first_striker"] == "b"


def test_a_side_fights_with_the_weapon_it_is_given(client: TestClient) -> None:
    """Naming the hand weapon puts the blade away, and the Lions then strike first."""
    report = fight(
        client,
        a={"unit": "white-lions-of-chrace", "size": 20, "weapon": "Hand Weapon"},
        b={"unit": "dwarf-warriors", "size": 20},
    )
    assert report["a"]["weapon"] == "Hand Weapon"
    assert report["first_striker"] == "a"


def test_charging_spearmen_fare_worse_than_receiving(client: TestClient) -> None:
    """The charger's rank rules lapse, so delivering the charge loses ground."""
    sides = {
        "a": {"unit": "elven-spearmen", "size": 20},
        "b": {"unit": "elven-spearmen", "size": 20},
    }
    standing = fight(client, **sides)
    charging = fight(client, **sides, charge={"side": "a", "full_inches": 8, "arc": "front"})
    assert charging["p_a_wins"] < standing["p_a_wins"]


def test_a_charge_into_the_rear_scores_for_the_charger(client: TestClient) -> None:
    """The arc a charge struck is worth combat-result points, so the rear beats the front."""
    sides = {
        "a": {"unit": "elven-spearmen", "size": 20},
        "b": {"unit": "elven-spearmen", "size": 20},
    }
    front = fight(client, **sides, charge={"side": "a", "full_inches": 8, "arc": "front"})
    rear = fight(client, **sides, charge={"side": "a", "full_inches": 8, "arc": "rear"})
    assert rear["p_a_wins"] > front["p_a_wins"]


def test_a_missile_unit_defaults_to_something_it_can_fight_with(client: TestClient) -> None:
    """Archers carry a Longbow last, and a bow has no Combat profile."""
    report = fight(
        client,
        a={"unit": "elven-archers", "size": 10},
        b={"unit": "dwarf-warriors", "size": 10},
    )
    assert report["a"]["weapon"] == "Hand Weapon"


def test_a_weapon_that_cannot_fight_is_refused_not_resolved(client: TestClient) -> None:
    """Naming the bow is a refusal at the boundary, not a resolver blowing up."""
    response = client.post(
        "/fight",
        json={
            "a": {"unit": "elven-archers", "size": 10, "weapon": "Longbow"},
            "b": {"unit": "dwarf-warriors", "size": 10},
        },
    )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "side a: Longbow has no Combat profile; it cannot be used here"
    }


def test_the_loser_takes_the_break_test(client: TestClient) -> None:
    """A side's three Break outcomes sum to the chance it lost the round."""
    report = fight(
        client,
        a={"unit": "white-lions-of-chrace", "size": 20},
        b={"unit": "dwarf-warriors", "size": 20},
    )
    # Only a loser tests, so a side's three outcomes exhaust the rounds it lost
    # -- which is exactly the chance its foe won.
    outcomes = sum(report["b"][key] for key in ("gives_ground", "falls_back", "breaks"))
    assert outcomes == pytest.approx(report["p_a_wins"])
    winner = sum(report["a"][key] for key in ("gives_ground", "falls_back", "breaks"))
    assert winner == pytest.approx(report["p_b_wins"])


def test_what_the_engine_did_not_apply_is_reported(client: TestClient) -> None:
    """A round says which printed rules it held without folding into the maths."""
    report = fight(
        client,
        a={"unit": "white-lions-of-chrace", "size": 20},
        b={"unit": "dwarf-warriors", "size": 20},
    )
    assert report["not_modelled"]
    assert all(isinstance(note, str) for note in report["not_modelled"])


def test_an_unknown_datasheet_is_a_404(client: TestClient) -> None:
    """A missed slug is not found, and says which slug was missed."""
    response = client.post(
        "/fight",
        json={"a": {"unit": "orcs", "size": 20}, "b": {"unit": "dwarf-warriors", "size": 20}},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "no unit 'orcs'"}


def test_a_weapon_the_side_does_not_carry_is_refused(client: TestClient) -> None:
    """A unit fights with what it carries, and the refusal names the side."""
    response = client.post(
        "/fight",
        json={
            "a": {"unit": "elven-spearmen", "size": 20, "weapon": "Chracian Great Blade"},
            "b": {"unit": "dwarf-warriors", "size": 20},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"].startswith("side a:")


def test_a_size_the_datasheet_forbids_is_refused(client: TestClient) -> None:
    """Below the printed minimum is refused, naming the side that asked."""
    response = client.post(
        "/fight",
        json={
            "a": {"unit": "elven-spearmen", "size": 20},
            "b": {"unit": "elven-spearmen", "size": 2},
        },
    )
    assert response.status_code == 422
    assert "side b" in response.json()["detail"]
