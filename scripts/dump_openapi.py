"""Write the API's OpenAPI document to a file, without serving it.

The frontend's TypeScript types are generated from this document, so the
Pydantic models the YAML validates against are the only place a datasheet's
shape is written down. Run it through ``make types``.
"""

import json
import sys
from pathlib import Path

from avelorn.api import app


def main() -> None:
    """Write the document to the path given as the first argument."""
    destination = Path(sys.argv[1])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(f"wrote {destination}")


if __name__ == "__main__":
    main()
