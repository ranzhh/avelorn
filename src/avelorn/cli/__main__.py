"""``python -m avelorn.cli``, the same entry point as the ``avelorn`` script."""

import sys

from avelorn.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
