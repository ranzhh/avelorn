"""Tabletop wargame toolkit: unit database, army list planner, and combat math."""

import logging

# Library code emits log records but installs no handlers; an application
# opts in via avelorn.core.logging.configure_logging(). The NullHandler
# keeps the package silent until then. See core/logging.py.
logging.getLogger(__name__).addHandler(logging.NullHandler())
