from __future__ import annotations

import json
import sys

import evolver
from util import trash_folders


def main(argv: list[str] | None = None, *, out=None, log_to=evolver.setup_logging) -> int:
    log_to()
    marked = trash_folders.marked_as(sys.argv[1:] if argv is None else argv)
    for video in marked:
        trash_folders.delete_permanently(video)
    print(json.dumps({"deleted": len(marked)}), file=out or sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
