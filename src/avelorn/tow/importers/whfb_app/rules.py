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

from avelorn.tow.schema.rule import Rule

from .parse import WhfbParseError
from .richtext import Node, text_of


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

    paragraphs = _paragraphs(fields.get("body"), warnings)
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
        )
    except ValidationError as err:
        raise WhfbParseError(f"{slug}: parsed fields do not validate: {err}") from err
    return RuleImport(rule=rule, warnings=warnings)


def _paragraphs(body: Node | None, warnings: list[str]) -> list[str]:
    if not body:
        return []
    paragraphs: list[str] = []
    for block in body.get("content", []):
        node_type = block.get("nodeType")
        text = text_of(block).strip()
        if not text:
            continue
        if node_type != "paragraph":
            warnings.append(f"body block {node_type!r} rendered as plain text: {text[:60]!r}")
        paragraphs.append(text)
    return paragraphs


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
