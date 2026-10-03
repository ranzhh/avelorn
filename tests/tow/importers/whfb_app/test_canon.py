"""Import-time canonicalisation: references rewritten to the corpus's spelling."""

from avelorn.tow.importers.whfb_app.canon import canonical, canonical_unit
from avelorn.tow.schema.unit import Unit

NAMES = ["Shortbow", "Fight In Extra Rank", "Cinderblast Bombs", "Armour Bane (X)"]


def test_canonical_meets_case_and_the_prose_plural_and_nothing_looser() -> None:
    """Case and a trailing plural "s" canonicalise; exact and unknown do not."""
    assert canonical("Fight in Extra Rank", NAMES) == "Fight In Extra Rank"
    assert canonical("shortbows", NAMES) == "Shortbow"
    assert canonical("Shortbow", NAMES) is None  # already exact: nothing to fix
    assert canonical("Longbow", NAMES) is None  # no entry: not this seam's call
    assert canonical("Cinderblast Bomb", NAMES) is None  # never depluralise the entry
    assert canonical("Armour Bane (1)", NAMES) is None  # a parameter, not a variant


def test_canonical_unit_rewrites_the_references_and_reports_each_fix() -> None:
    """The Reavers' shape: a replace-option gaining the prose plural of an entry."""
    unit = Unit.model_validate(
        {
            "id": "riders",
            "name": "Riders",
            "points": 10,
            "unit_size": {"min": 5},
            "troop_type": "Light Cavalry",
            "profiles": [
                {
                    "name": "Rider",
                    "M": 9,
                    "WS": 4,
                    "BS": 4,
                    "S": 3,
                    "T": 3,
                    "W": 1,
                    "I": 4,
                    "A": 1,
                    "Ld": 8,
                }
            ],
            "equipment": ["Hand Weapon"],
            "options": [
                {
                    "name": "Shortbows",
                    "kind": "equipment",
                    "points": 1,
                    "per_model": True,
                    "adds_equipment": ["Shortbows"],
                    "removes_equipment": ["Cavalry Spear"],
                }
            ],
        }
    )
    fixed, fixes = canonical_unit(unit, equipment=["Shortbow", "Cavalry Spear", "Hand Weapon"])
    assert fixed.options[0].adds_equipment == ["Shortbow"]
    assert fixed.options[0].removes_equipment == ["Cavalry Spear"]
    assert fixed.options[0].name == "Shortbows"  # a label, not a reference
    assert fixes == ["reference 'Shortbows' canonicalised to 'Shortbow'"]
