"""Where this corpus departs from the source on purpose.

Every entry under ``data/`` opens with the page it was scraped from, and
the importer owns those fields outright: a re-import overwrites them. A
correction edits one of them, so carrying it across is not enough. It is
reapplied to the fresh scrape on every import.

A correction is one RFC 6902 operation plus the value the source is
expected to hold. The expectation is the whole mechanism. It is checked
before the operation runs, so a correction that no longer describes the
source fails the import instead of silently re-breaking data the source
has since put right.

``path`` is a JSON Pointer into the entry as serialized, so it is
positional: ``/profiles/2/name`` addresses the third profile. A source
that reorders a list moves the pointer under the correction, which
``expect`` catches. The correction is refused rather than applied to the
wrong row.
"""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Correction(BaseModel):
    """One deliberate departure from what the source states."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["add", "remove", "replace"]
    path: str = Field(pattern=r"^(/[^/]*)+$")  # JSON Pointer
    # What the source holds today. Checked before `op` runs, so a source
    # that has since been fixed fails the import rather than being
    # silently re-broken. Meaningless for `add`, whose precondition is
    # that nothing is there.
    expect: Any = None
    value: Any = None
    why: str  # why the source is wrong, citing what says otherwise

    @model_validator(mode="after")
    def _operands_match_the_operation(self) -> Self:
        if self.op == "add":
            if self.expect is not None:
                raise ValueError(
                    "`add` takes no `expect`: its precondition is that nothing is there"
                )
        elif self.expect is None:
            raise ValueError(
                f"`{self.op}` needs an `expect`: the value the source is stated to hold"
            )
        if self.op == "remove":
            if self.value is not None:
                raise ValueError("`remove` takes no `value`")
        elif self.value is None:
            raise ValueError(f"`{self.op}` needs a `value`")
        return self
