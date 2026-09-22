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
