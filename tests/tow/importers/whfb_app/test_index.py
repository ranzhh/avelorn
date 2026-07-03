"""The client's rules-index extraction from homepage HTML."""

from avelorn.tow.importers.whfb_app.client import WhfbAppClient

_HTML = b"""
<html><body>
  <a href="/the-combat-phase">The Combat Phase</a>
  <a href="/the-combat-phase/roll-to-hit-combat">Roll to Hit</a>
  <a href="/special-rules/killing-blow">Killing Blow</a>
  <a href="/army/high-elf-realms">High Elf Realms</a>
  <a href="/the-combat-phase">dup, kept once</a>
  <a href="/">home</a>
  <a href="/_next/static/css/app.css">asset</a>
  <a href="/faq#errata">anchor stripped, whole link dropped</a>
  <a href="https://example.com/off-site">external</a>
</body></html>
"""


def test_index_extracts_unique_sorted_page_paths(monkeypatch) -> None:
    """Content pages only: no root, no assets, no off-site, deduped, sorted."""
    client = WhfbAppClient(contact_email="test@example.com")
    monkeypatch.setattr(client, "_get", lambda url: _HTML)
    assert client.index() == [
        "army/high-elf-realms",
        "special-rules/killing-blow",
        "the-combat-phase",
        "the-combat-phase/roll-to-hit-combat",
    ]
