"""Guards on what the importer's YAML writer puts on paper."""

import yaml

from avelorn.tow.data import TOWRepository
from avelorn.tow.importers.whfb_app.yamlout import (
    _option_row,
    armour_to_yaml,
    rule_to_yaml,
    weapon_to_yaml,
)
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import OptionKind, UnitOption
from avelorn.tow.schema.weapon import Weapon

REPO = TOWRepository()


def test_option_row_writes_every_field_of_the_schema() -> None:
    """A field added to UnitOption must be written, not silently dropped.

    The writer names its keys one by one to control their printed order,
    so nothing tells it about a new field. Two options are needed to cover
    the schema: the cost shapes are mutually exclusive.
    """
    flat = UnitOption(
        name="Cinderblast Bombs",
        kind=OptionKind.EQUIPMENT,
        applies_to="Ironbeard",
        points=15,
        per_model=True,
        adds_rules=["Drilled"],
        removes_rules=["Valour of Ages"],
        adds_equipment=["Cinderblast Bombs"],
        removes_equipment=["Shield"],
        limit="0-1 unit per 1000 points",
    )
    budget = UnitOption(name="Magic standard", kind=OptionKind.MAGIC_STANDARD, points_budget=50)

    written = set(_option_row(flat)) | set(_option_row(budget))
    assert written == set(UnitOption.model_fields)


def _written(text: str) -> set[str]:
    """The top-level keys a rendered document carries.

    Returns:
        The mapping's keys.
    """
    return set(yaml.safe_load(text))


def test_weapon_writer_emits_every_schema_field() -> None:
    """A weapon field the writer forgets is dropped on the next re-import."""
    weapon = REPO.weapons["longbow"].model_copy(update={"notes": "Printed usage restriction."})
    assert weapon.weapon_type and weapon.notes  # the premise: every field is set
    assert _written(weapon_to_yaml(weapon)) == set(Weapon.model_fields)


def test_rule_writer_emits_every_schema_field() -> None:
    """Likewise for a rule: effects and notes are hand-authored and easy to lose."""
    rule = REPO.rules["strike-first"].model_copy(
        update={"notes": "What the engine does with it.", "flavour": "Quicksilver.", "page": 177}
    )
    assert rule.effects and rule.notes and rule.category  # the premise
    assert _written(rule_to_yaml(rule)) == set(Rule.model_fields)


def test_armour_writer_emits_every_schema_field() -> None:
    """Armour's two value shapes are exclusive, so it takes two documents."""
    suit = REPO.armoury["heavy-armour"].model_copy(update={"notes": "Restriction."})
    addition = REPO.armoury["shield"]
    assert suit.armour_value and addition.armour_value_improvement  # the premise
    written = _written(armour_to_yaml(suit)) | _written(armour_to_yaml(addition))
    assert written == set(Armour.model_fields)
