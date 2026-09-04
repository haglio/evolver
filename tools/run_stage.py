"""Run one stage on its own, logging to the console:

    python tools/run_stage.py watch_weights

From a worktree this runs the branch's copy of the stage against the real
library, which is how a stage is shown before it lands.  Only a stage whose
``run()`` takes no arguments can be run this way; the upscales are the
pipeline's to call.
"""

from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python tools/run_stage.py <tasks module name>", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    stage = importlib.import_module(f"tasks.{argv[0]}")
    print(stage.run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
