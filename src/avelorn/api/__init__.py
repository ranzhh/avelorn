"""The ``avelorn`` HTTP surface: a window on the corpus under ``data/``.

Serve it with ``fastapi dev src/avelorn/api/app.py`` (``make serve``), or point
any ASGI server at :data:`avelorn.api.app`.
"""

from avelorn.api.app import app

__all__ = ["app"]
