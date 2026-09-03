"""The two surfaces show the same unit: a drift guard over the CLI and the API.

Both are windows on one corpus, so a field added to the schema must reach both
or neither. These tests fail when one surface learns something the other has
not.
"""

from fastapi.testclient import TestClient

from avelorn.api.app import app, corpus
from avelorn.cli import commands
from avelorn.core.registry import Registry
from avelorn.tow.data import TOWRepository
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.correction import Correction
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon
from avelorn.tow.views import RuleSummary, UnitSummary, WeaponSummary

REPO = TOWRepository()
app.dependency_overrides[corpus] = lambda: REPO
CLIENT = TestClient(app)

# A datasheet that populates every field: two profiles, equipment, rules,
# options, a base size, and a resolved troop-type profile.
SLUG = "elven-archers"


_CORRECTION = Correction(op="replace", path="/name", expect="Wrong", value="Right", why="a test's")
_CAVEATS = "What this build does not model about it."


def _annotated(attribute: str, kind: str, slug: str) -> list[str]:
    """What the terminal prints for an entry carrying both hand-authored fields.

    No weapon, armour entry or datasheet under data/ carries either today,
    so the guard is held against an entry made here. It stays honest
    whether or not the corpus happens to carry one that day.

    Returns:
        The lines `avelorn <kind> show` prints for it.
    """
    registry = getattr(REPO, attribute)
    annotated = registry[slug].model_copy(
        update={"caveats": _CAVEATS, "corrections": [_CORRECTION]}
    )
    repo = TOWRepository()
    repo.__dict__[attribute] = Registry(
        (annotated if entry.id == slug else entry for entry in registry.values()), kind=kind
    )
    return getattr(commands, f"show_{kind}")(repo, slug)


def _caveats_are_shown(printed: list[str]) -> bool:
    """Whether the terminal prints what the build leaves out.

    Returns:
        Whether the heading reached the output.
    """
    return "Not covered:" in "\n".join(printed)


def _corrections_are_shown(printed: list[str]) -> bool:
    """Whether the terminal prints an entry's departures from the source.

    Returns:
        Whether the heading reached the output.
    """
    return "Corrected from the source:" in "\n".join(printed)


def test_the_listing_carries_the_same_fields_on_both() -> None:
    """One shared view backs `avelorn units` and `GET /units`."""
    served = CLIENT.get("/units").json()
    assert set(served[0]) == set(UnitSummary.model_fields)

    listed = commands.list_units(REPO)
    header, rows = listed[0], listed[1:]
    assert len(header.split()) - 1 == len(UnitSummary.model_fields)  # PTS/MODEL is one column
    assert len(rows) == len(served)


def test_the_listing_shows_the_same_values_on_both() -> None:
    """The terminal row and the JSON object describe the same unit."""
    served = next(u for u in CLIENT.get("/units").json() if u["id"] == SLUG)
    row = next(line for line in commands.list_units(REPO) if line.startswith(SLUG))
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
    printed = "\n".join(commands.show_unit(REPO, SLUG))
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
        "caveats": _caveats_are_shown(_annotated("units", "unit", SLUG)),
        "corrections": _corrections_are_shown(_annotated("units", "unit", SLUG)),
    }
    assert set(shown) == set(Unit.model_fields)
    assert [field for field, found in shown.items() if not found] == []


def test_the_rule_listing_carries_the_same_fields_on_both() -> None:
    """One shared view backs `avelorn rules list` and `GET /rules`."""
    served = CLIENT.get("/rules").json()
    assert set(served[0]) == set(RuleSummary.model_fields)

    listed = commands.list_rules(REPO)
    assert len(listed[0].split()) - 1 == len(RuleSummary.model_fields)  # PRINTED BY is one column
    assert len(listed) - 1 == len(served)


def test_the_unmodelled_report_names_the_same_rules_on_both() -> None:
    """Both surfaces total the same honesty, down to who prints each rule."""
    served = CLIENT.get("/rules/unmodelled").json()
    printed = "\n".join(commands.list_unmodelled(REPO))
    for rule in served:
        assert rule["name"] in printed
        for slug in (*rule["units"], *rule["weapons"]):
            assert slug in printed
    assert f"{len(served)} printed rules have no entry" in printed


def test_show_rule_covers_every_field_the_detail_endpoint_serves() -> None:
    """`avelorn rules show` prints all of `Rule`, which is what `GET /rules/{slug}` returns."""
    served = CLIENT.get("/rules/stubborn").json()
    assert set(served) == set(Rule.model_fields)

    rule = REPO.rules["stubborn"]
    printed = "\n".join(commands.show_rule(REPO, "stubborn"))
    shown = {
        "id": rule.id in printed,
        "name": rule.name in printed,
        "page": f"page {rule.page}" in printed,
        "category": (rule.category or "") in printed,
        "flavour": rule.flavour is None or rule.flavour.split()[0] in printed,
        "paragraphs": all(p.split()[0] in printed for p in rule.paragraphs),
        "effects": "fall-back-in-good-order" in printed,
        "caveats": "Not covered:" in printed,
        "corrections": _corrections_are_shown(_annotated("rules", "rule", "stubborn")),
    }
    assert set(shown) == set(Rule.model_fields)
    assert [field for field, found in shown.items() if not found] == []


def test_the_weapon_listing_carries_the_same_fields_on_both() -> None:
    """One shared view backs `avelorn weapons list` and `GET /weapons`."""
    served = CLIENT.get("/weapons").json()
    assert set(served[0]) == set(WeaponSummary.model_fields)

    listed = commands.list_weapons(REPO)
    assert len(listed[0].split()) == len(WeaponSummary.model_fields)
    assert len(listed) - 1 == len(served)


def test_show_weapon_covers_every_field_the_detail_endpoint_serves() -> None:
    """`avelorn weapons show` prints all of `Weapon`, which is what the route returns.

    Two entries, because no weapon populates every field: the Longbow records a
    family and prints no restriction, the Lance the other way round.
    """
    assert set(CLIENT.get("/weapons/longbow").json()) == set(Weapon.model_fields)

    longbow, lance = REPO.weapons["longbow"], REPO.weapons["lance"]
    assert lance.notes is not None
    lines = commands.show_weapon(REPO, "longbow")
    typed = "\n".join(lines)
    restricted = "\n".join(commands.show_weapon(REPO, "lance")).replace("\n  ", " ")
    covered = {
        "id": longbow.id in typed,
        "name": longbow.name in typed,
        # The family is checked on its own line: every weapon carrying a type is
        # a bow, so a substring match would pass off the name alone.
        "weapon_type": longbow.weapon_type is not None and lines[1] == longbow.weapon_type.value,
        "profiles": str(longbow.profiles[0].range) in typed,
        "notes": lance.notes[:40] in restricted,
        "caveats": _caveats_are_shown(_annotated("weapons", "weapon", "longbow")),
        "corrections": _corrections_are_shown(_annotated("weapons", "weapon", "longbow")),
    }
    assert set(covered) == set(Weapon.model_fields)
    assert all(covered.values()), [field for field, ok in covered.items() if not ok]


def test_the_armour_listing_shows_every_entry_on_both() -> None:
    """`avelorn armour list` and `GET /armour` cover the same entries."""
    served = CLIENT.get("/armour").json()
    assert set(served[0]) == set(Armour.model_fields)
    assert len(commands.list_armour(REPO)) - 1 == len(served)


def test_show_armour_covers_every_field_the_detail_endpoint_serves() -> None:
    """`avelorn armour show` prints all of `Armour`, which is what the route returns.

    Two entries again: Heavy Armour carries a value of its own, a Shield carries
    an improvement and a restriction instead.
    """
    assert set(CLIENT.get("/armour/heavy-armour").json()) == set(Armour.model_fields)

    heavy, shield = REPO.armoury["heavy-armour"], REPO.armoury["shield"]
    assert shield.notes is not None
    valued = "\n".join(commands.show_armour(REPO, "heavy-armour"))
    worn = "\n".join(commands.show_armour(REPO, "shield")).replace("\n  ", " ")
    covered = {
        "id": heavy.id in valued,
        "name": heavy.name in valued,
        "armour_value": f"{heavy.armour_value}+" in valued,
        "armour_value_improvement": str(shield.armour_value_improvement) in worn,
        "notes": shield.notes[:30] in worn,
        "caveats": _caveats_are_shown(_annotated("armoury", "armour", "shield")),
        "corrections": _corrections_are_shown(_annotated("armoury", "armour", "shield")),
    }
    assert set(covered) == set(Armour.model_fields)
    assert all(covered.values()), [field for field, ok in covered.items() if not ok]
