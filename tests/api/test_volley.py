"""Resolving a volley of shooting, and the panic it causes, over the wire."""

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


def volley(client: TestClient, **body: object) -> dict:
    """Resolve a volley, failing loudly on a refusal.

    Returns:
        The report.
    """
    response = client.post("/volley", json=body)
    assert response.status_code == 200, response.json()
    return response.json()


def test_a_shooter_looses_the_weapon_it_can_shoot_with(client: TestClient) -> None:
    """Archers carry a hand weapon too, and the volley takes the bow."""
    report = volley(
        client,
        shooter={"unit": "elven-archers", "size": 10},
        target={"unit": "dwarf-warriors", "size": 20},
    )
    assert report["shooter"]["weapon"] == "Longbow"
    assert report["shots"] > 0


def test_the_reported_hit_target_is_the_one_the_volley_used(client: TestClient) -> None:
    """Beyond half range the same bow needs a worse roll, and fells fewer."""
    sides = {
        "shooter": {"unit": "elven-archers", "size": 10},
        "target": {"unit": "dwarf-warriors", "size": 20},
    }
    close = volley(client, **sides, distance=12)
    far = volley(client, **sides, distance=25)
    assert far["hit_target"] > close["hit_target"]
    assert far["expected_casualties"] < close["expected_casualties"]


def test_an_unknown_distance_is_left_unapplied_and_said_so(client: TestClient) -> None:
    """The long-range modifier cannot be settled without a distance, so it is not guessed."""
    sides = {
        "shooter": {"unit": "elven-archers", "size": 10},
        "target": {"unit": "dwarf-warriors", "size": 20},
    }
    unknown = volley(client, **sides)
    known = volley(client, **sides, distance=12)
    assert len(unknown["not_modelled"]) > len(known["not_modelled"])


def test_the_outcome_is_a_distribution(client: TestClient) -> None:
    """Wounds and casualties are each a full distribution over what could happen."""
    report = volley(
        client,
        shooter={"unit": "elven-archers", "size": 10},
        target={"unit": "dwarf-warriors", "size": 20},
        distance=12,
    )
    assert sum(report["wounds"]) == pytest.approx(1.0)
    assert sum(report["casualties"]) == pytest.approx(1.0)
    assert report["expected_casualties"] <= report["expected_wounds"]


def test_the_panic_outcomes_exhaust_what_can_happen(client: TestClient) -> None:
    """A unit holds, falls back, flees or is wiped out; nothing else."""
    report = volley(
        client,
        shooter={"unit": "elven-archers", "size": 10},
        target={"unit": "dwarf-warriors", "size": 5},
        distance=12,
    )
    panic = report["panic"]
    outcomes = panic["holds"] + panic["falls_back"] + panic["flees"] + panic["destroyed"]
    assert outcomes == pytest.approx(1.0)


def test_a_bigger_unit_is_far_less_likely_to_be_shaken(client: TestClient) -> None:
    """Panic needs a quarter of the unit, which a big one rarely loses to one volley.

    Rarely, not never: the volley is a distribution, and its tail reaches a
    quarter of twenty models with a probability worth four in ten thousand.
    """
    sides = {"shooter": {"unit": "elven-archers", "size": 10}, "distance": 12}
    small = volley(client, **sides, target={"unit": "dwarf-warriors", "size": 5})
    big = volley(client, **sides, target={"unit": "dwarf-warriors", "size": 20})
    assert 0 < big["panic"]["tests"] < small["panic"]["tests"] / 100


def test_a_depleted_unit_flees_where_a_fresh_one_falls_back(client: TestClient) -> None:
    """The split is against the battle strength, not the size being shot at.

    Five models is a whole unit or the remains of twenty, and the rules part
    them: above half its battle strength it falls back, at or below it flees.
    """
    sides = {
        "shooter": {"unit": "elven-archers", "size": 10},
        "target": {"unit": "dwarf-warriors", "size": 5},
        "distance": 12,
    }
    fresh = volley(client, **sides)
    depleted = volley(client, **sides, battle_strength=20)
    assert fresh["panic"]["falls_back"] > depleted["panic"]["falls_back"]
    assert depleted["panic"]["flees"] > fresh["panic"]["flees"]


def test_a_shooter_that_moved_hits_one_point_harder(client: TestClient) -> None:
    """Moving and Shooting is a corpus rule the caller could not reach before.

    A deployment is stationary, so the rule was honoured by never applying. The
    same volley from a unit that marched hits on a 4+ rather than a 3+.
    """
    shot = {
        "shooter": {"unit": "elven-archers", "size": 10},
        "target": {"unit": "dwarf-warriors", "size": 20},
        "distance": 6,
    }
    still = volley(client, **shot)
    marched = volley(client, **shot, moved=True)

    assert still["hit_target"] == 3
    assert marched["hit_target"] == 4
    assert marched["expected_casualties"] < still["expected_casualties"]


def test_a_weapon_that_cannot_shoot_is_refused(client: TestClient) -> None:
    """A hand weapon has no missile profile, and the refusal says which side asked."""
    response = client.post(
        "/volley",
        json={
            "shooter": {"unit": "elven-archers", "size": 10, "weapon": "Hand Weapon"},
            "target": {"unit": "dwarf-warriors", "size": 20},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"].startswith("shooter: Hand Weapon has no missile profile")


def test_a_unit_carrying_nothing_to_shoot_with_is_refused(client: TestClient) -> None:
    """Dwarf Warriors carry no missile weapon at all."""
    response = client.post(
        "/volley",
        json={
            "shooter": {"unit": "dwarf-warriors", "size": 10},
            "target": {"unit": "elven-archers", "size": 10},
        },
    )
    assert response.status_code == 422
    assert "nothing it carries has a missile profile" in response.json()["detail"]


def test_an_unknown_datasheet_is_a_404(client: TestClient) -> None:
    """A missed slug is not found, and says which slug was missed."""
    response = client.post(
        "/volley",
        json={
            "shooter": {"unit": "goblins", "size": 10},
            "target": {"unit": "dwarf-warriors", "size": 20},
        },
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "no unit 'goblins'"}
