"""A double-keyed registry: entities addressed by slug, resolved by name.

Pure collection machinery, no game knowledge: anything carrying an ``id``
slug and a display ``name`` can be registered. The two keys serve the two
lookup roles. Addressing — which entry, ``registry["longbow"]`` — goes
through the mapping interface by slug. Resolving a display-name reference
— what does "Longbow" on a datasheet point at? — goes through
:meth:`Registry.by_name`, which raises on a miss so an unknown name can
never pass silently: the caller decides whether that is an error or
something to degrade visibly.
"""

from collections.abc import Iterable, Iterator, Mapping
from typing import Protocol

from avelorn.core.errors import AvelornError


class Keyed(Protocol):
    """Anything registrable: a slug identity and a printed display name."""

    id: str
    name: str


class UnknownNameError(AvelornError, LookupError):
    """No registered entry carries the requested display name."""

    def __init__(self, kind: str, name: str) -> None:
        """Record which ``kind`` of registry missed which ``name``."""
        super().__init__(f"no {kind} named {name!r}")
        self.kind = kind
        self.name = name


class Registry[T: Keyed](Mapping[str, T]):
    """Entities double-keyed by slug and by display name.

    The mapping interface addresses by slug (``registry["longbow"]``,
    ``in``, iteration, ``values()``); :meth:`by_name` resolves a printed
    display name. Both keys must be unique across the registry, so a
    collision fails at construction, not on some later lookup.
    """

    def __init__(self, items: Iterable[T] = (), *, kind: str = "entry") -> None:
        """Index ``items`` by slug and by name; ``kind`` labels error messages.

        Raises:
            ValueError: two items share a slug or a display name.
        """
        self._kind = kind
        self._by_slug: dict[str, T] = {}
        self._by_name: dict[str, T] = {}
        for item in items:
            if item.id in self._by_slug:
                raise ValueError(f"duplicate {kind} slug {item.id!r}")
            if item.name in self._by_name:
                raise ValueError(f"duplicate {kind} name {item.name!r}")
            self._by_slug[item.id] = item
            self._by_name[item.name] = item

    def __getitem__(self, slug: str) -> T:
        """The entry addressed by ``slug``.

        Returns:
            The registered entry.
        """
        return self._by_slug[slug]

    def __iter__(self) -> Iterator[str]:
        """Iterate the slugs, in registration order.

        Returns:
            An iterator over the slugs.
        """
        return iter(self._by_slug)

    def __len__(self) -> int:
        """The number of registered entries.

        Returns:
            The entry count.
        """
        return len(self._by_slug)

    def by_name(self, name: str) -> T:
        """Resolve a printed display name to its entry.

        Returns:
            The entry whose ``name`` matches exactly.

        Raises:
            UnknownNameError: no entry carries ``name`` — the caller
                decides whether to fail or to degrade visibly.
        """
        try:
            return self._by_name[name]
        except KeyError:
            raise UnknownNameError(self._kind, name) from None

    def resolve(self, names: Iterable[str]) -> tuple[list[T], list[str]]:
        """Resolve printed display names in bulk, tolerating misses.

        The counterpart of :meth:`by_name` for callers to whom an unknown
        name is data rather than an error: nothing raises, and the misses
        come back for the caller to report.

        Returns:
            The resolved entries and the unknown names, each in input order.
        """
        found: list[T] = []
        missing: list[str] = []
        for name in names:
            if (item := self._by_name.get(name)) is not None:
                found.append(item)
            else:
                missing.append(name)
        return found, missing
