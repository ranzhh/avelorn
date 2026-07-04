"""Re-importing a rule must not lose its hand-authored effects."""

from pathlib import Path

import pytest
import yaml

from avelorn.core.loading import load_yaml
from avelorn.tow.data import DATA_DIR, TOWRepository
from avelorn.tow.importers.whfb_app.parse import WhfbParseError
from avelorn.tow.importers.whfb_app.rules import with_existing_effects
from avelorn.tow.importers.whfb_app.yamlout import rule_to_yaml
from avelorn.tow.schema.rule import Rule

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
    merged, warnings = with_existing_effects(_REIMPORTED, path)
    assert merged.effects == existing.effects
    assert merged.paragraphs == ["Fresh text."]
    assert any("re-verify" in w for w in warnings)


def test_unchanged_text_preserves_without_warning(tmp_path: Path) -> None:
    """Same printed text: effects carry over silently."""
    existing = REPO.rules["armour-bane"]
    path = _existing(tmp_path, rule_to_yaml(existing))
    fresh = existing.model_copy(update={"effects": []})
    merged, warnings = with_existing_effects(fresh, path)
    assert merged.effects == existing.effects
    assert warnings == []


def test_no_existing_file_is_a_plain_import(tmp_path: Path) -> None:
    """Nothing to preserve: the scraped rule passes through unchanged."""
    merged, warnings = with_existing_effects(_REIMPORTED, tmp_path / "armour-bane.yaml")
    assert merged is _REIMPORTED
    assert warnings == []


def test_invalid_existing_file_refuses_to_overwrite(tmp_path: Path) -> None:
    """A file that no longer validates is never silently clobbered."""
    path = _existing(tmp_path, "id: armour-bane\nname: broken\n")  # no paragraphs
    with pytest.raises(WhfbParseError, match="refusing to overwrite"):
        with_existing_effects(_REIMPORTED, path)


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda p: p.stem)
def test_rule_files_round_trip(path: Path) -> None:
    """Serialising a loaded rule file and reloading it loses nothing.

    The invariant that makes preservation safe: rule_to_yaml emits every
    field the schema carries, effects included.
    """
    original = load_yaml(path, Rule)
    reloaded = Rule.model_validate(yaml.safe_load(rule_to_yaml(original)))
    assert reloaded == original
