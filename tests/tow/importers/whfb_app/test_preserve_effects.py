"""Re-importing must not lose what was written by hand, not scraped."""

from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel

from avelorn.core.loading import load_yaml
from avelorn.tow.data import DATA_DIR, TOWRepository
from avelorn.tow.importers.whfb_app.parse import WhfbParseError
from avelorn.tow.importers.whfb_app.preserve import HAND_AUTHORED, with_hand_authored
from avelorn.tow.importers.whfb_app.yamlout import rule_to_yaml, weapon_to_yaml
from avelorn.tow.schema.armour import Armour
from avelorn.tow.schema.rule import Rule
from avelorn.tow.schema.weapon import Weapon

RULE_FILES = sorted(DATA_DIR.glob("tow/rules/*.yaml"))
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
    field the schema carries, effects included.
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
    """A rule's modelling notes are hand-authored, and are not lost."""
    held = REPO.rules["stubborn"]
    assert held.notes  # the premise: the real file has them
    path = tmp_path / "stubborn.yaml"
    path.write_text(rule_to_yaml(held))
    scraped = held.model_copy(update={"notes": None, "effects": []})

    merged, _ = with_hand_authored(scraped, path)
    assert merged.notes == held.notes


def test_modifier_effect_prints_the_rulebook_key() -> None:
    """A set operation is written as `set`, not the model's keyword-safe name."""
    rendered = rule_to_yaml(REPO.rules["strike-first"])
    assert "- set:" in rendered
    assert "set_" not in rendered
