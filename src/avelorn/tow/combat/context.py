"""The engagement context: the situation a volley is resolved in.

The printed home of these facts is the sequence's first sub-phase —
"Choose Unit & Declare Target", where range and line of sight are
checked. Every field defaults to unknown (None): a conditional rule
that needs an unknown answer stays unfactored and reported, exactly
like any other thing the math cannot honour — it is never guessed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EngagementContext:
    """What is known about the situation of the shooting unit."""

    moved: bool | None = None  # "moved for any reason during this turn"
    distance: int | None = None  # inches to the target
