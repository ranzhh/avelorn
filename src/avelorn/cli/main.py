"""The ``avelorn`` command line: a terminal window onto the corpus under ``data/``.

Parsing and dispatch only — both command bodies are in
:mod:`avelorn.cli.commands`, so what the CLI reads stays separate from how its
flags are spelt.

It reads the database and nothing else. The engine's resolutions — a volley, a
round of close combat, a break test, a folded question spanning two turns — are
reachable from Python and from the demo scripts, and are deliberately not
flags here: the vocabulary for posing them as questions is still to be
designed, and mirroring each resolver's signature into options would fix the
wrong shape in place.
"""

import argparse
import sys

from avelorn.cli import commands
from avelorn.core.errors import AvelornError
from avelorn.tow.data import TOWRepository, default_repository


def main(argv: list[str] | None = None) -> int:
    """Run the CLI.

    Returns:
        The process exit code: 0 for an answer, 2 for a question the corpus
        will not answer.
    """
    args = _parser().parse_args(argv)
    # The corpus as data, not as a game in play: these commands read the
    # database, and assembling a TOWGame would resolve every phase's rules
    # in force to answer a question about a datasheet.
    data = default_repository()
    # The process edge, where an engine error becomes a message: an unknown
    # slug is the user's question being refused, not a bug to dump a traceback
    # for.
    try:
        lines = _dispatch(args, data)
    except (AvelornError, LookupError) as refused:
        # To stderr: a shell reading piped output must not find an error
        # message where a datasheet should be.
        print(f"error: {refused}", file=sys.stderr)
        return 2
    for line in lines:
        print(line)
    return 0


def _parser() -> argparse.ArgumentParser:
    """Build the argument parser: the two commands the corpus answers.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(prog="avelorn")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("units", help="list every datasheet in the corpus")
    show = sub.add_parser("show", help="print one datasheet")
    show.add_argument("slug")
    return parser


def _dispatch(args: argparse.Namespace, data: TOWRepository) -> list[str]:
    """Run the named command.

    Returns:
        The lines to print.
    """
    if args.command == "units":
        return commands.units(data)
    return commands.show(data, args.slug)
