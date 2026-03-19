#!/usr/bin/env python3
"""evolver.py - video collection maintenance pipeline.

Runs on a 15-minute Task Scheduler trigger. Stages:
  1. sort    - move new videos from inbox into sorted folders by source/orientation
  2. upscale - apply Topaz frame interpolation + 4x upscale to sorted videos
"""

import logging
import subprocess
import sys

import config
from tasks import sort, upscale


def setup_logging():
    config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(config.LOG_FILE, encoding="utf-8")],
    )


def check_dependencies():
    if not config.FFMPEG.is_file():
        raise RuntimeError(f"Topaz ffmpeg not found: {config.FFMPEG}")
    if subprocess.run(["ffprobe", "-version"], capture_output=True).returncode != 0:
        raise RuntimeError("ffprobe not found in PATH")


def main():
    setup_logging()
    log = logging.getLogger(__name__)

    try:
        check_dependencies()
    except RuntimeError as e:
        log.error("Dependency check failed: %s", e)
        sys.exit(1)

    sort_result = sort.run()
    log.info("")

    if sort_result.moved == 0:
        log.info("No new videos moved from inbox. Skipping Stage 2.")
        sys.exit(0)

    upscale_result = upscale.run()
    sys.exit(1 if upscale_result.failed > 0 else 0)


if __name__ == "__main__":
    main()
