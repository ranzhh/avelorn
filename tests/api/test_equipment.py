"""Serving the weapons and armour a datasheet prints, and resolving its names."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from avelorn.api.app import app, corpus
from avelorn.tow.data import TOWRepository
from avelorn.tow.views import UnitDetail

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


def test_the_weapon_listing_says_which_phase_can_use_each(client: TestClient) -> None:
    """A bow shoots and cannot fight, so a caller arming a melee is not offered it."""
    listed = {weapon["id"]: weapon for weapon in client.get("/weapons").json()}
    assert listed["longbow"]["shoots"] is True
    assert listed["longbow"]["fights"] is False
    assert listed["great-weapon"]["fights"] is True
    assert listed["great-weapon"]["shoots"] is False


def test_a_weapon_resolves_its_rules_per_profile(client: TestClient) -> None:
    """A Lance prints Armour Bane (1), filed under the template it comes from."""
    body = client.get("/weapons/lance").json()
    printed = body["profiles"][0]["special_rules"]
    assert printed == [{"name": "Armour Bane (1)", "kind": "rule", "slug": "armour-bane"}]


def test_two_profiles_keep_the_rules_each_one_prints(client: TestClient) -> None:
    """Drakefire Pistols carry Quick Shot when fired and Extra Attacks in combat.

    Pooling the two would say the pistols do both at once.
    """
    body = client.get("/weapons/brace-of-drakefire-pistols").json()
    by_profile = {
        profile["name"]: {rule["name"] for rule in profile["special_rules"]}
        for profile in body["profiles"]
    }
    assert "Quick Shot" in by_profile["Ranged"]
    assert "Quick Shot" not in by_profile["Combat"]
    assert "Extra Attacks (+1)" in by_profile["Combat"]


def test_armour_is_served_whole(client: TestClient) -> None:
    """A shield has no armour value of its own and improves the one it is worn with."""
    body = client.get("/armour/shield").json()
    assert body["armour_value"] is None
    assert body["armour_value_improvement"] == 1
    assert "Requires Two Hands" in body["notes"]


def test_a_datasheet_says_which_registry_each_printed_name_sits_in(client: TestClient) -> None:
    """Equipment mixes weapons and armour in one list, so the kind is the server's to say."""
    body = client.get("/units/dragon-princes").json()
    kinds = {item["name"]: item["kind"] for item in body["equipment"]}
    assert kinds["Lance"] == "weapon"
    assert kinds["Shield"] == "armour"
    assert all(item["slug"] for item in body["equipment"])


def test_a_name_filed_as_both_a_weapon_and_a_rule_resolves_to_one_of_them(
    client: TestClient,
) -> None:
    """Daith's Reaper is a weapon entry and the rule that weapon carries.

    The slug alone cannot tell them apart, which is why a reference carries the
    kind: following the weapon and following the rule are different routes.
    """
    assert client.get("/weapons/daiths-reaper").status_code == 200
    assert client.get("/rules/daiths-reaper").status_code == 200

    weapon = client.get("/weapons/daiths-reaper").json()
    printed = [rule for profile in weapon["profiles"] for rule in profile["special_rules"]]
    assert {"name": "Daith's Reaper", "kind": "rule", "slug": "daiths-reaper"} in printed


def test_every_printed_equipment_name_in_the_corpus_resolves(client: TestClient) -> None:
    """A name resolving to nothing would be a dead chip in any browser over this."""
    unresolved = []
    for slug in REPO.units:
        for item in client.get(f"/units/{slug}").json()["equipment"]:
            if item["slug"] is None:
                unresolved.append((slug, item["name"]))
    assert unresolved == []


def test_an_unknown_slug_is_a_404(client: TestClient) -> None:
    """The miss names what was looked for, on both new routes."""
    assert client.get("/weapons/no-such-weapon").status_code == 404
    assert client.get("/armour/no-such-armour").status_code == 404
    assert "no-such-weapon" in client.get("/weapons/no-such-weapon").json()["detail"]


def test_equipment_matching_no_entry_carries_neither_kind_nor_slug() -> None:
    """Nothing in the corpus prints such a name, so this is the latent path.

    A reference is followable or it is not, and both fields go together: a kind
    without a slug would send a caller to a route with nothing behind it.
    """
    doctored = REPO.units["elven-archers"].model_copy(
        update={"equipment": ["Hand Weapon", "Trousers of Great Antiquity"]}
    )
    resolved = UnitDetail.of(doctored, REPO).equipment

    assert resolved[0].kind == "weapon"
    assert resolved[0].slug == "hand-weapon"
    assert resolved[1].name == "Trousers of Great Antiquity"
    assert resolved[1].kind is None
    assert resolved[1].slug is None
