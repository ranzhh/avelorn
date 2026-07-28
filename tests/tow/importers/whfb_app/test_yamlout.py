"""Guards on what the importer's YAML writer puts on paper."""

from avelorn.tow.importers.whfb_app.yamlout import _option_row
from avelorn.tow.schema.unit import OptionKind, UnitOption


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
