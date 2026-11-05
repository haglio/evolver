from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from tasks.frame_of_video_backfill import run

if __name__ == "__main__":
    print(run(config.METADATA_DIR, apply="--apply" in sys.argv[1:]))
