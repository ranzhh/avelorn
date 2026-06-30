"""Console logging setup for Avelorn applications.

Library code never configures logging. Modules obtain a logger with
``logging.getLogger(__name__)`` and emit records; whether those records
reach a console, a file, or nowhere is an application-level decision made
once at process start by calling :func:`configure_logging` (from a
script, and later the CLI / API entry points). The ``avelorn`` package
installs a ``NullHandler`` (see ``avelorn/__init__.py``) so that, absent
such a call, the library stays silent instead of emitting "No handlers
could be found" warnings.

:func:`configure_logging` configures the *root* logger, so a single
console handler and format covers every logger in the process: the
library's ``avelorn.*`` loggers, the entry-point script's own
``__main__`` logger, and any dependency that logs through the standard
library. Configuring only the ``avelorn`` logger would silently miss the
scripts, which run as ``__main__``.

The format is deliberately plain text aimed at a terminal. Moving to a
JSON line format for an ELK pipeline later is a matter of swapping the
formatter built here; call sites elsewhere do not change.

Call-site convention: pass log data as ``%``-style arguments, not
f-strings -- ``logger.info("resolved %s", army)`` -- so the message
string stays constant and formatting is deferred until a handler
actually emits the record. The ``G`` (flake8-logging-format) lint rules
enforce this.
"""

import logging

# Each field is bracketed so the timestamp, level, and logger name stay
# unambiguous delimiters; the message is left bare because it is free text
# that may itself contain brackets or quotes. No explicit datefmt, so the
# default formatter appends milliseconds (e.g. 16:51:11,432).
_LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """Install a plain-text console handler on the root logger.

    Call once from an application entry point. Configures the root logger
    so records from every logger -- the ``avelorn.*`` library loggers,
    the entry point's own ``__main__`` logger, and standard-library
    dependencies -- are emitted with one format.

    Idempotent: the root handler list is replaced rather than appended
    to, so repeated calls (e.g. one script importing another that also
    configures) do not stack handlers and double-log.

    Output goes to stderr, leaving stdout free for a program's payload
    (tables, generated YAML).

    Args:
        level: Minimum level to emit, e.g. ``logging.DEBUG`` for verbose
            runs. Defaults to ``logging.INFO``.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
