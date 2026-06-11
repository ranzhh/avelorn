"""Walkers for the Contentful rich-text documents in whfb.app payloads.

A rich-text document is a tree of JSON nodes (`nodeType`, `content`, ...)
whose `entry-hyperlink` / `embedded-entry-*` nodes carry the linked entry
inline. The importer needs three views of a document: its visible text,
the `rule` entries it links to, and the (possibly nested) bullet-list
structure that encodes unit options.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Node = dict[str, Any]

_LINK_NODE_TYPES = {"entry-hyperlink", "embedded-entry-inline", "embedded-entry-block"}


def _link_target(node: Node) -> Node | None:
    if node.get("nodeType") not in _LINK_NODE_TYPES:
        return None
    return node.get("data", {}).get("target")


def _entry_content_type(entry: Node) -> str | None:
    return entry.get("sys", {}).get("contentType", {}).get("sys", {}).get("id")


def text_of(node: Node, *, links_as_names: bool = False) -> str:
    """Render a node's visible text.

    Links render as their display text by default, or as the linked entry's
    canonical `name` with `links_as_names=True` (display text varies in case
    and number, e.g. "thrusting spears" linking to "Thrusting Spear").

    Returns:
        The concatenated text of the node's subtree.
    """
    if node.get("nodeType") == "text":
        return node["value"]
    if links_as_names:
        target = _link_target(node)
        if target is not None:
            name = target.get("fields", {}).get("name")
            if name:
                return name
    return "".join(
        text_of(child, links_as_names=links_as_names) for child in node.get("content", [])
    )


def linked_rules(node: Node) -> list[tuple[str, str]]:
    """Collect the `rule` links under `node`.

    Returns:
        A (display text, entry name) pair per link, in document order.
    """
    pairs: list[tuple[str, str]] = []

    def walk(n: Node) -> None:
        target = _link_target(n)
        if target is not None and _entry_content_type(target) == "rule":
            name = target.get("fields", {}).get("name")
            if name:
                pairs.append((text_of(n).strip(), name))
        for child in n.get("content", []):
            walk(child)

    walk(node)
    return pairs


def linked_rule_names(node: Node, *, as_displayed: bool = False) -> list[str]:
    """Name the `rule` entries linked anywhere under `node`.

    By default this is the linked entry's canonical `name`; with
    `as_displayed=True` it is the link's visible text instead — the name as
    printed in context (e.g. the "Detachment" rule links to the entry named
    "Detachment Special Rules", a rules-section page).

    Returns:
        The names in document order, deduplicated.
    """
    names: list[str] = []
    for display, name in linked_rules(node):
        value = (display or name) if as_displayed else name
        if value not in names:
            names.append(value)
    return names


@dataclass
class OptionLine:
    """One bullet line of an options document."""

    text: str  # visible text with links rendered as canonical entry names
    rules: list[str]  # `rule` entries linked on this line, in order


def _own_line(item: Node) -> OptionLine:
    """Render a list item without its nested list.

    Returns:
        The item's own text and links.
    """
    direct = [
        child
        for child in item.get("content", [])
        if child.get("nodeType") not in ("unordered-list", "ordered-list")
    ]
    wrapper: Node = {"content": direct}
    text = " ".join(text_of(wrapper, links_as_names=True).split())
    return OptionLine(text=text, rules=linked_rule_names(wrapper))


def option_lines(doc: Node) -> list[tuple[OptionLine, list[OptionLine]]]:
    """Split an options document into its top-level bullet items.

    Returns:
        One (line, sub-items) pair per item: a flat option is `(line, [])`,
        a group ("Any unit may:" followed by a nested list) is
        `(header, [sub-lines...])`.
    """
    items: list[tuple[OptionLine, list[OptionLine]]] = []
    for block in doc.get("content", []):
        if block.get("nodeType") not in ("unordered-list", "ordered-list"):
            # Stray paragraphs (usually empty) appear after the list; surface
            # non-empty ones as flat lines so nothing is dropped silently.
            stray = " ".join(text_of(block, links_as_names=True).split())
            if stray:
                items.append((OptionLine(text=stray, rules=linked_rule_names(block)), []))
            continue
        for item in block.get("content", []):
            children = [
                _own_line(sub)
                for child in item.get("content", [])
                if child.get("nodeType") in ("unordered-list", "ordered-list")
                for sub in child.get("content", [])
            ]
            items.append((_own_line(item), children))
    return items
