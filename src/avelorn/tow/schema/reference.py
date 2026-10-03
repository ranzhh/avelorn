"""A reference to a rule entry: its slug, and the X it is printed with.

YAML writes an unparameterised reference as the bare slug and a parameterised
one as ``{rule: <slug>, X: <value>}``. X is unsigned; the rule's printed name
carries any sign, and the rule's ``parameter`` says what X may be.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]


class RuleRef(BaseModel):
    """A rule as a datasheet, a weapon profile, a troop type or a grant names it."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    rule: Slug
    x: Annotated[int, Field(ge=0)] | str | None = Field(default=None, alias="X")

    @model_validator(mode="before")
    @classmethod
    def _bare_slug(cls, data: object) -> object:
        return {"rule": data} if isinstance(data, str) else data

    @model_serializer(mode="plain")
    def _as_written(self) -> str | dict[str, int | str]:
        return self.rule if self.x is None else {"rule": self.rule, "X": self.x}

    def __str__(self) -> str:
        """The reference as YAML writes it, for an error message.

        Returns:
            The bare slug, or the ``{rule, X}`` mapping.
        """
        return self.rule if self.x is None else f"{{rule: {self.rule}, X: {self.x}}}"
