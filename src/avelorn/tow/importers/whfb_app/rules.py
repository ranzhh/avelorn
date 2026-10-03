"""Map whfb.app Special Rules pages onto the rule schema.

A rules page embeds the printed rule as Contentful rich text: an italic
flavour line (`description`) and body paragraphs. The text is kept
verbatim as displayed — links render as their display text, not their
target's canonical name — because the file's job is to be diffable
against the printed rule. As elsewhere, nothing is guessed silently:
body structure the parser does not expect becomes a warning for the
reviewing human.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from avelorn.tow.schema.rule import PrintedParameter, Rule, prints_x

from .parse import WhfbParseError
from .richtext import Node, text_of

_CONTAINER_BLOCKS = frozenset({"document", "unordered-list", "list-item"})
_TEXT_BLOCKS = frozenset({"paragraph", *(f"heading-{level}" for level in range(1, 7))})


@dataclass
class RuleImport:
    """A parsed rule plus everything the parser was unsure about."""

    rule: Rule
    warnings: list[str]


def parse_special_rule(entry: Node) -> RuleImport:
    """Parse a Special Rules page entry into a Rule.

    Returns:
        The rule and the warnings raised while mapping it.

    Raises:
        WhfbParseError: The page has no name, slug, or body text.
    """
    fields = entry.get("fields", {})
    slug = fields.get("slug")
    name = fields.get("name")
    if not slug or not name:
        raise WhfbParseError(f"rule entry has no slug/name: {fields.keys()}")
    warnings: list[str] = []

    body = fields.get("body")
    paragraphs = _block_paragraphs(body, warnings) if body else []
    if not paragraphs:
        raise WhfbParseError(f"{slug}: rule body has no text")

    flavour = None
    if description := fields.get("description"):
        flavour = text_of(description).strip() or None

    category = _category(fields.get("ruleType"), warnings)

    try:
        rule = Rule(
            id=slug,
            name=name,
            page=fields.get("pageReference"),
            category=category,
            flavour=flavour,
            paragraphs=paragraphs,
            parameter=PrintedParameter(kind="printed") if prints_x(name) else None,
        )
    except ValidationError as err:
        raise WhfbParseError(f"{slug}: parsed fields do not validate: {err}") from err
    return RuleImport(rule=rule, warnings=warnings)


def _block_paragraphs(block: Node, warnings: list[str]) -> list[str]:
    node_type = block.get("nodeType")
    if node_type in _CONTAINER_BLOCKS:
        return [
            text
            for child in block.get("content", [])
            for text in _block_paragraphs(child, warnings)
        ]
    text = text_of(block).strip()
    if not text:
        return []
    if node_type not in _TEXT_BLOCKS:
        warnings.append(f"body block {node_type!r} rendered as plain text: {text[:60]!r}")
    return [text]


def _category(rule_type: object, warnings: list[str]) -> str | None:
    if not isinstance(rule_type, list) or not rule_type:
        return None
    if len(rule_type) > 1:
        warnings.append(f"multiple rule types; kept the first of {len(rule_type)}")
    first = rule_type[0]
    if not isinstance(first, dict):
        return None
    fields = first.get("fields")
    if not isinstance(fields, dict):
        return None
    name = fields.get("name")
    return name if isinstance(name, str) and name else None
