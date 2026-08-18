"""The importer's drift check: what the site changed under data/."""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[4] / "scripts" / "import_whfb_app.py"
_spec = importlib.util.spec_from_file_location("import_whfb_app", _SCRIPT)
assert _spec and _spec.loader
importer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(importer)

_URL = "https://tow.whfb.app/weapons-of-war/light-armour"


def _armour_entry(value: int) -> dict:
    """A Weapons of War page entry for an armour suit of the given value.

    Returns:
        The entry as the client hands it to the parser.
    """
    text = {"nodeType": "text", "value": f"Armour Value: {value}+"}
    return {
        "fields": {
            "slug": "light-armour",
            "name": "Light Armour",
            "body": {"content": [{"nodeType": "paragraph", "content": [text]}]},
        }
    }


class _StubClient:
    """A client that serves one armour page, at a value the test picks."""

    def __init__(self, value: int) -> None:
        self.value = value
        self.calls = 0

    def weapons_of_war_entry(self, slug: str) -> dict:
        """Serve the stubbed page.

        Returns:
            The armour entry.
        """
        self.calls += 1
        return _armour_entry(self.value)


@pytest.fixture
def held(tmp_path: Path) -> Path:
    """An armour file as data/ holds it: Light Armour at 6+.

    Returns:
        The written file's path.
    """
    path = tmp_path / "tow" / "armour" / "light-armour.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(f"# Source: {_URL}\nid: light-armour\nname: Light Armour\narmour_value: 6\n")
    return path


def test_check_passes_when_the_page_still_matches(held: Path, capsys) -> None:
    """A file the site still agrees with reports no drift and prints nothing."""
    assert importer._check(_StubClient(6), [held.parent], data_dir=held.parents[2]) is True
    assert capsys.readouterr().out == ""


def test_check_reports_a_changed_page_as_a_diff(held: Path, capsys) -> None:
    """A changed value fails the check and shows the difference both ways."""
    assert importer._check(_StubClient(5), [held], data_dir=held.parents[2]) is False
    printed = capsys.readouterr().out
    assert "-armour_value: 6" in printed
    assert "+armour_value: 5" in printed
    assert "(held)" in printed and "(site)" in printed


def test_check_ignores_formatting_and_hand_authored_comments(tmp_path: Path, capsys) -> None:
    """Only what the importer owns is compared: layout and notes are not drift."""
    path = tmp_path / "light-armour.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Source: {_URL}\n"
        "# Hand-authored note the site knows nothing about.\n"
        'name: "Light Armour"\n'
        "id: light-armour\n"  # same data, different order, quoting and comments
        "armour_value:   6\n"
    )
    assert importer._check(_StubClient(6), [path], data_dir=tmp_path) is True
    assert capsys.readouterr().out == ""


def test_check_leaves_hand_authored_files_alone(tmp_path: Path) -> None:
    """A file with no source header was never imported: never re-read."""
    path = tmp_path / "troop-type.yaml"
    path.write_text("name: Heavy Infantry\n")
    client = _StubClient(6)
    assert importer._check(client, [path], data_dir=tmp_path) is True
    assert client.calls == 0


def test_check_writes_nothing(held: Path) -> None:
    """The check is read-only: the file on disk is untouched by drift."""
    before = held.read_text()
    importer._check(_StubClient(5), [held], data_dir=held.parents[2])
    assert held.read_text() == before


def test_data_files_expands_directories_and_keeps_files(tmp_path: Path) -> None:
    """A directory contributes the YAML beneath it; a named file is kept."""
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "one.yaml").write_text("")
    (nested / "notes.md").write_text("")
    named = tmp_path / "two.yaml"
    named.write_text("")
    assert importer._data_files([tmp_path / "a", named]) == [nested / "one.yaml", named]
