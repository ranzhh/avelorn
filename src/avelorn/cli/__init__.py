"""The ``avelorn`` command line: a window on the corpus under ``data/``.

It reads the database — the datasheets and what they may take — and owns no
maths. What the engine resolves is not reachable here yet; see
:mod:`avelorn.cli.main` for why.
"""

from avelorn.cli.main import main

__all__ = ["main"]
