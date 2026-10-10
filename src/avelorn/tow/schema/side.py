"""The two parties of an attack, as the rulebook names them."""

from enum import StrEnum


class Side(StrEnum):
    """A party of one attack: the attacker making it, or the target suffering it."""

    ATTACKER = "attacker"
    TARGET = "target"

    @property
    def other(self) -> "Side":
        """The other party of the same attack."""
        return Side.TARGET if self is Side.ATTACKER else Side.ATTACKER
