"""The two surfaces show the same unit: a drift guard over the CLI and the API.

Both are windows on one corpus, so a field added to the schema must reach both
or neither. These tests fail when one surface learns something the other has
not.
"""

from fastapi.testclient import TestClient

from avelorn.api.app import app, corpus
from avelorn.cli import commands
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.unit import Unit
from avelorn.tow.views import UnitSummary

REPO = TOWRepository()
app.dependency_overrides[corpus] = lambda: REPO
CLIENT = TestClient(app)

# A datasheet that populates every field: two profiles, equipment, rules,
# options, a base size, and a resolved troop-type profile.
SLUG = "elven-archers"


def test_the_listing_carries_the_same_fields_on_both() -> None:
    """One shared view backs `avelorn units` and `GET /units`."""
    served = CLIENT.get("/units").json()
    assert set(served[0]) == set(UnitSummary.model_fields)

    listed = commands.units(REPO)
    header, rows = listed[0], listed[1:]
    assert len(header.split()) - 1 == len(UnitSummary.model_fields)  # PTS/MODEL is one column
    assert len(rows) == len(served)


def test_the_listing_shows_the_same_values_on_both() -> None:
    """The terminal row and the JSON object describe the same unit."""
    served = next(u for u in CLIENT.get("/units").json() if u["id"] == SLUG)
    row = next(line for line in commands.units(REPO) if line.startswith(SLUG))
    for value in (served["name"], str(served["points"]), served["troop_type"]):
        assert value in row


def test_show_covers_every_field_the_detail_endpoint_serves() -> None:
    """`avelorn show` prints all of `Unit`, which is what `GET /units/{slug}` returns.

    The checklist is explicit so that a new schema field fails here until the
    terminal learns to print it, rather than silently appearing over HTTP only.
    """
    served = CLIENT.get(f"/units/{SLUG}").json()
    assert set(served) == set(Unit.model_fields)

    unit = REPO.units[SLUG]
    printed = "\n".join(commands.show(REPO, SLUG))
    shown = {
        "id": unit.id in printed,
        "name": unit.name in printed,
        "points": f"{unit.points} points per model" in printed,
        "unit_size": f"unit size {unit.unit_size.min}+" in printed,
        "troop_type": unit.troop_type.value in printed,
        "troop_type_profile": "rank bonus up to" in printed,
        "base_size": "25 x 25 mm" in printed,
        "profiles": all(profile.name in printed for profile in unit.profiles),
        "equipment": all(item in printed for item in unit.equipment),
        "special_rules": all(rule in printed for rule in unit.special_rules),
        "options": all(option.name in printed for option in unit.options),
    }
    assert set(shown) == set(Unit.model_fields)
    assert [field for field, found in shown.items() if not found] == []
