"""Resolve the rule names a page prints to references into the corpus."""

from collections.abc import Callable, Iterable, Sequence

from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import Rule, printed_base

from .canon import canonical
from .client import WhfbAppError
from .parse import Refer, WhfbParseError, slugified


class RuleReferences:
    """The corpus's rules, as the importer resolves printed names against them.

    A printed name resolves by the entry's exact name or an alias (the name of
    the entry a page's link targets), then by a loose spelling of it (case, a
    trailing plural "s"), then by the name less its bracket, then by its slug.
    ``fetch`` reads a rule page by slug for a name no entry answers to; without
    it that name fails the import. ``stubs`` are the entries fetched so far,
    for the caller to write once the import succeeds.
    """

    def __init__(self, rules: Iterable[Rule], fetch: Callable[[str], Rule] | None = None) -> None:
        self._by_name: dict[str, Rule] = {}
        self._by_base: dict[str, Rule] = {}
        self._by_id: dict[str, Rule] = {}
        for rule in rules:
            self._index(rule)
        self._fetch = fetch
        self.stubs: list[Rule] = []

    def at(self, where: str) -> Refer:
        """Resolve names printed on one entry, which errors name.

        Returns:
            A resolver for names printed at ``where`` ("unit maneaters").
        """
        return lambda printed, *aliases: self.resolve(printed, where, aliases)

    def resolve(self, printed: str, where: str, aliases: Sequence[str] = ()) -> RuleRef:
        """The reference a printed name makes, or failing that one of its aliases.

        Returns:
            The slug, with the X the bracket prints.

        Raises:
            WhfbParseError: the bracket does not read as the entry's X, naming
                where it is printed, the name and the X the entry expects; or
                no entry answers to the name and none can be fetched.
        """
        entry, spelled = self._entry(printed, aliases)
        if entry is None:
            stub = self._stub(printed, where)
            entry, spelled = self._entry(printed, aliases)
            if entry is None:
                raise WhfbParseError(f"{where}: {printed!r}: the site files it as {stub.name!r}")
        try:
            return entry.read(spelled)
        except ValueError as err:
            raise WhfbParseError(f"{where}: {printed!r}: {err}") from err

    def _index(self, rule: Rule) -> None:
        self._by_name[rule.name] = rule
        self._by_base[rule.base] = rule
        self._by_id[rule.id] = rule

    def _entry(self, printed: str, aliases: Sequence[str]) -> tuple[Rule | None, str]:
        for name in (printed, *aliases, canonical(printed, self._by_name)):
            if name is not None and name in self._by_name:
                return self._by_name[name], _spelled(self._by_name[name], printed)
        base = printed_base(printed)
        for name in (base, canonical(base, self._by_base)):
            if name is not None and name in self._by_base:
                return self._by_base[name], printed
        entry = self._by_id.get(slugified(base))
        return (entry, _spelled(entry, printed)) if entry is not None else (None, printed)

    def _stub(self, printed: str, where: str) -> Rule:
        """Fetch the rule no entry answers to, as a text-only stub.

        Returns:
            The stub, now among the rules names resolve against.

        Raises:
            WhfbParseError: there is nothing to fetch it with, the site has no
                such page, or the page is an entry the corpus already holds.
        """
        slug = slugified(printed_base(printed))
        if self._fetch is None:
            raise WhfbParseError(f"{where}: {printed!r}: no rule entry; import rule {slug}")
        try:
            stub = self._fetch(slug)
        except WhfbAppError as err:
            raise WhfbParseError(f"{where}: {printed!r}: no rule entry nor page {slug}") from err
        if stub.id in self._by_id:
            held = self._by_id[stub.id].name
            raise WhfbParseError(
                f"{where}: {printed!r}: the site files it as {stub.id}, held as {held!r}"
            )
        self.stubs.append(stub)
        self._index(stub)
        return stub


def _spelled(entry: Rule, printed: str) -> str:
    """The name to read against ``entry``: its own, unless the print adds a bracket.

    Returns:
        The entry's name for a match that differs only in spelling, otherwise
        what was printed, so a bracket the entry does not take fails the read.
    """
    if entry.parameter is None and _bracket(printed) in (None, _bracket(entry.name)):
        return entry.name
    return printed


def _bracket(name: str) -> str | None:
    base = printed_base(name)
    return None if base == name else name.removeprefix(base).casefold()
