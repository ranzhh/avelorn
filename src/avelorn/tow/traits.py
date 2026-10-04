"""Characteristic traits."""

from collections.abc import Hashable, Iterator
from dataclasses import dataclass
from typing import Protocol

from avelorn.core.distribution import Distribution
from avelorn.core.graph import Modifier, Source
from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.unit import Characteristic


class Profiled[V](Protocol):
    """Anything that answers a characteristic."""

    def characteristic(self, c: Characteristic) -> V: ...


class Carries(Protocol):
    """Anything that gives its holder rules."""

    def sources(self) -> Iterator[tuple[RuleRef, Source]]: ...


@dataclass(frozen=True)
class Operand[V: Hashable]:
    """A value in force at a step."""

    value: Distribution[V]
    printed: V
    changes: tuple[Modifier, ...] = ()
