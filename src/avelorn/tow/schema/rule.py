"""Rule models for Warhammer: The Old World.

A rule entry carries the printed rule verbatim: name, flavour line, and
body paragraphs as displayed on the page. It deliberately has no
structured mechanics yet — executable effects are a separate, later
concern and will be authored alongside this text so they can be diffed
against what the rulebook actually says.
"""

from pydantic import BaseModel, ConfigDict, Field


class Rule(BaseModel):
    """A rules-page entry (special rule or core rule), text verbatim."""

    model_config = ConfigDict(extra="forbid")

    id: str  # stable slug, e.g. "armour-bane"
    name: str  # printed name, e.g. "Armour Bane (X)"
    page: int | None = None  # rulebook page reference
    category: str | None = None  # site rule category, e.g. "Special Rules"
    flavour: str | None = None  # italic flavour line, if any
    paragraphs: list[str] = Field(min_length=1)  # rule text, as displayed
