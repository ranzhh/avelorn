"""Re-importing must not lose what was written by hand, nor silently re-break what it corrects."""

from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from avelorn.core.loading import load_yaml
from avelorn.tow.data import TOWRepository, rule_paths
from avelorn.tow.importers.whfb_app.merge import (
    HAND_AUTHORED,
    StaleCorrection,
    with_hand_authored,
)
from avelorn.tow.importers.whfb_app.parse import WhfbParseError
from avelorn.tow.importers.whfb_app.yamlout import rule_to_yaml, unit_to_yaml, weapon_to_yaml
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.correction import Correction
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.unit import Unit
from avelorn.tow.schema.weapon import Weapon

RULE_FILES = rule_paths()
REPO = TOWRepository()

_REIMPORTED = Rule(id="armour-bane", name="Armour Bane (X)", paragraphs=["Fresh text."])


def _existing(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "armour-bane.yaml"
    path.write_text(source)
    return path


def test_effects_survive_a_reimport(tmp_path: Path) -> None:
    """Hand-authored effects carry over onto the freshly scraped rule.

    The fresh text differs from the file's, so the merge also warns that
    the preserved effects need re-verifying — the FAQ/errata reread case.
    """
    existing = REPO.rules["armour-bane"]
    assert existing.effects  # the premise: the real file has them
    path = _existing(tmp_path, rule_to_yaml(existing))
    merged, warnings = with_hand_authored(_REIMPORTED, path)
    assert merged.effects == existing.effects
    assert merged.paragraphs == ["Fresh text."]
    assert any("re-verify" in w for w in warnings)


def test_unchanged_text_preserves_without_warning(tmp_path: Path) -> None:
    """Same printed text: effects carry over silently."""
    existing = REPO.rules["armour-bane"]
    path = _existing(tmp_path, rule_to_yaml(existing))
    fresh = existing.model_copy(update={"effects": []})
    merged, warnings = with_hand_authored(fresh, path)
    assert merged.effects == existing.effects
    assert warnings == []


def test_no_existing_file_is_a_plain_import(tmp_path: Path) -> None:
    """Nothing to preserve: the scraped rule passes through unchanged."""
    merged, warnings = with_hand_authored(_REIMPORTED, tmp_path / "armour-bane.yaml")
    assert merged is _REIMPORTED
    assert warnings == []


def test_invalid_existing_file_refuses_to_overwrite(tmp_path: Path) -> None:
    """A file that no longer validates is never silently clobbered."""
    path = _existing(tmp_path, "id: armour-bane\nname: broken\n")  # no paragraphs
    with pytest.raises(WhfbParseError, match="refusing to overwrite"):
        with_hand_authored(_REIMPORTED, path)


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda p: p.stem)
def test_rule_files_round_trip(path: Path) -> None:
    """Serialising a loaded rule file and reloading it loses nothing.

    The invariant that makes preservation safe: rule_to_yaml emits every
    field the schema carries, effects and overlay included.
    """
    original = load_yaml(path, Rule)
    reloaded = Rule.model_validate(yaml.safe_load(rule_to_yaml(original)))
    assert reloaded == original


@pytest.mark.parametrize(
    ("model", "scraped"),
    [
        (Rule, {"id", "name", "page", "category", "flavour", "paragraphs"}),
        (Weapon, {"id", "name", "profiles", "notes"}),
        (Armour, {"id", "name", "armour_value", "armour_value_improvement", "notes"}),
        (
            Unit,
            {
                "id",
                "name",
                "points",
                "unit_size",
                "troop_type",
                "troop_type_profile",
                "base_size",
                "profiles",
                "equipment",
                "special_rules",
                "options",
            },
        ),
    ],
    ids=lambda value: getattr(value, "__name__", ""),
)
def test_every_field_is_either_scraped_or_hand_authored(
    model: type[BaseModel], scraped: set[str]
) -> None:
    """A new schema field must be classified, not silently dropped on re-import.

    The importer overwrites what it scrapes and carries the rest across.
    A field in neither set would be written as its default the next time
    the entry is re-imported, quietly discarding whatever was there.
    """
    assert scraped | HAND_AUTHORED[model] == set(model.model_fields)
    assert not scraped & HAND_AUTHORED[model]


def test_weapon_type_survives_a_reimport(tmp_path: Path) -> None:
    """A weapon's hand-set rulebook family is not scraped, and is not lost."""
    held = REPO.weapons["longbow"]
    assert held.weapon_type  # the premise: the real file has one
    path = tmp_path / "longbow.yaml"
    path.write_text(weapon_to_yaml(held))
    scraped = held.model_copy(update={"weapon_type": None})

    merged, warnings = with_hand_authored(scraped, path)
    assert merged.weapon_type == held.weapon_type
    assert warnings == []


def test_rule_notes_survive_a_reimport(tmp_path: Path) -> None:
    """A rule's caveats are hand-authored, and are not lost."""
    held = REPO.rules["stubborn"]
    assert held.caveats  # the premise: the real file has them
    path = tmp_path / "stubborn.yaml"
    path.write_text(rule_to_yaml(held))
    scraped = held.model_copy(update={"caveats": None, "effects": []})

    merged, _ = with_hand_authored(scraped, path)
    assert merged.caveats == held.caveats


def test_modifier_effect_prints_the_rulebook_key() -> None:
    """A set operation is written as `set`, not the model's keyword-safe name."""
    rendered = rule_to_yaml(REPO.rules["strike-first"])
    assert "- set:" in rendered
    assert "set_" not in rendered


# --- corrections ------------------------------------------------------


def _held_with(unit: Unit, *corrections: Correction) -> Unit:
    return unit.model_copy(update={"corrections": list(corrections)})


_MOUNT = Correction(
    op="replace",
    path="/profiles/2/name",
    expect="Elven Steed",
    value="Barded Elven Steed",
    why="the datasheet prints a barded steed",
)


def _as_scraped(unit: Unit, name: str = "Elven Steed") -> Unit:
    """The datasheet as the uncorrected source states it.

    Returns:
        The datasheet with the mount row named as the source names it.
    """
    profiles = [
        p.model_copy(update={"name": name}) if i == 2 else p for i, p in enumerate(unit.profiles)
    ]
    return unit.model_copy(update={"profiles": profiles, "corrections": []})


def test_a_correction_is_reapplied_to_every_reimport(tmp_path: Path) -> None:
    """The source states the wrong thing; the corpus keeps stating the right one."""
    held = _held_with(REPO.units["silver-helms"], _MOUNT)
    path = tmp_path / "silver-helms.yaml"
    path.write_text(unit_to_yaml(held))

    merged, _ = with_hand_authored(_as_scraped(held), path)
    assert merged.profiles[2].name == "Barded Elven Steed"
    assert merged.corrections == [_MOUNT]


def test_a_correction_the_source_has_fixed_stops_the_import(tmp_path: Path) -> None:
    """The alarm: a correction that no longer describes the source refuses to reapply.

    Silently reapplying it would re-break data the source has since put
    right, and nothing would say so.
    """
    held = _held_with(REPO.units["silver-helms"], _MOUNT)
    path = tmp_path / "silver-helms.yaml"
    path.write_text(unit_to_yaml(held))

    with pytest.raises(StaleCorrection, match="expects 'Elven Steed'"):
        with_hand_authored(_as_scraped(held, "Barded Elven Steed"), path)


def test_a_correction_addressing_nothing_stops_the_import(tmp_path: Path) -> None:
    """A pointer into a profile the source no longer has is not applied blind."""
    held = _held_with(
        REPO.units["silver-helms"],
        _MOUNT.model_copy(update={"path": "/profiles/9/name"}),
    )
    path = tmp_path / "silver-helms.yaml"
    path.write_text(unit_to_yaml(held))

    with pytest.raises(StaleCorrection, match="addresses nothing"):
        with_hand_authored(_as_scraped(held), path)


def test_an_added_rule_the_source_now_prints_stops_the_import(tmp_path: Path) -> None:
    """`add` has no RFC 6902 precondition, so staleness is checked directly."""
    correction = Correction(
        op="add",
        path="/special_rules/-",
        value="Fear",
        why="the datasheet prints Fear; the source omits it",
    )
    held = _held_with(REPO.units["silver-helms"], correction)
    path = tmp_path / "silver-helms.yaml"
    path.write_text(unit_to_yaml(held))
    scraped = held.model_copy(update={"corrections": []})

    added, _ = with_hand_authored(scraped, path)
    assert added.special_rules[-1] == "Fear"

    fixed = scraped.model_copy(update={"special_rules": [*scraped.special_rules, "Fear"]})
    with pytest.raises(StaleCorrection, match="already states it"):
        with_hand_authored(fixed, path)


def test_a_correction_cannot_reach_the_hand_authored_fields(tmp_path: Path) -> None:
    """They are lifted off before the patch, so a correction cannot address `why`."""
    held = _held_with(
        REPO.units["silver-helms"],
        _MOUNT.model_copy(update={"path": "/corrections/0/why"}),
    )
    path = tmp_path / "silver-helms.yaml"
    path.write_text(unit_to_yaml(held))

    with pytest.raises(StaleCorrection, match="addresses nothing"):
        with_hand_authored(_as_scraped(held), path)


def test_corrections_need_the_operands_their_operation_takes() -> None:
    """A correction that cannot be gated is refused at the schema."""
    with pytest.raises(ValueError, match="needs an `expect`"):
        Correction(op="replace", path="/points", value=24, why="...")
    with pytest.raises(ValueError, match="takes no `expect`"):
        Correction(op="add", path="/special_rules/-", expect="x", value="Fear", why="...")
    with pytest.raises(ValueError, match="needs a `value`"):
        Correction(op="replace", path="/points", expect=23, why="...")
