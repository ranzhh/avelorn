"""Stable references from printed corpus text to catalogued items."""

from pydantic import BaseModel, ConfigDict, Field


class RuleRef(BaseModel):
    """One printed rule reference, addressed by its stable rule id.

    ``printed`` remains the text the owning page used. ``rule`` is the identity
    used to find the catalogued rule, so a page spelling can differ without
    becoming a different rule.
    """

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(alias="rule")
    printed: str


type RuleReference = str | RuleRef


def printed_name(reference: RuleReference) -> str:
    """Return the spelling the owning corpus entry prints.

    Returns:
        The reference's printed spelling.
    """
    return reference.printed if isinstance(reference, RuleRef) else reference


def same_rule(left: RuleReference, right: RuleReference) -> bool:
    """Whether two references identify the same rule.

    Two explicit references compare by id; legacy strings retain their exact
    printed-name comparison until their owning field is migrated.

    Returns:
        Whether the references identify the same rule.
    """
    if isinstance(left, RuleRef) and isinstance(right, RuleRef):
        return left.rule_id == right.rule_id
    return left == right
