"""Resolve the rule names a page prints to references into the corpus.

A page prints "Armour Bane (1)" where a datasheet writes
``{rule: armour-bane, X: 1}``. A printed name resolves by the entry's exact
name or an alias (the name of the entry a page's link targets, where the link
displays other text), then by a loose spelling of it (case, a trailing plural
"s"; see :func:`~avelorn.tow.importers.whfb_app.canon.canonical`), then by the
name less its bracket, the bracket read as the X the entry declares, its sign
checked against the entry's name. A name no entry answers to is fetched from
the site as a text-only stub, which the import writes beside what it imports.
"""

from collections.abc import Callable, Iterable, Sequence

from avelorn.tow.schema.reference import RuleRef
from avelorn.tow.schema.rule import Rule, printed_base

from .canon import canonical
from .parse import Refer, WhfbParseError, slugified


class RuleReferences:
    """The corpus's rules, as the importer resolves printed names against them.

    ``fetch`` reads a rule page by slug; without it a name no entry answers to
    fails the import. ``stubs`` are the entries fetched so far, for the caller
    to write.
    """

    def __init__(self, rules: Iterable[Rule], fetch: Callable[[str], Rule] | None = None) -> None:
        """Index ``rules`` by name and by the name less its bracket."""
        self._rules = {rule.name: rule for rule in rules}
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

    def _entry(self, printed: str, aliases: Sequence[str]) -> tuple[Rule | None, str]:
        names = list(self._rules)
        for name in (printed, *aliases, canonical(printed, names)):
            if name is not None and name in self._rules:
                entry = self._rules[name]
                return entry, printed if entry.parameter is not None else entry.name
        base = printed_base(printed)
        if base == printed:
            return None, printed
        bases = {rule.base: rule for rule in self._rules.values()}
        found = base if base in bases else canonical(base, list(bases))
        return (bases[found], printed) if found is not None else (None, printed)

    def _stub(self, printed: str, where: str) -> Rule:
        """Fetch the rule no entry answers to, as a text-only stub.

        Returns:
            The stub, now among the rules names resolve against.

        Raises:
            WhfbParseError: there is nothing to fetch it with.
        """
        slug = slugified(printed_base(printed))
        if self._fetch is None:
            raise WhfbParseError(f"{where}: {printed!r}: no rule entry; import rule {slug}")
        stub = self._fetch(slug)
        self.stubs.append(stub)
        self._rules[stub.name] = stub
        return stub
