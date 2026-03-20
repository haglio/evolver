#!/usr/bin/env python3
"""evolver.py - video collection maintenance pipeline.

Runs on a 15-minute Task Scheduler trigger. Stages:
  1. sort    - move new videos from inbox into sorted folders by source/orientation
  2. purge   - remove weird outputs and their matching sources
  3. upscale - apply Topaz frame interpolation + 4x upscale to sorted videos
  4. dupes   - scan 1_sorted for likely duplicate videos by exact filesize
  5. verify  - check 1_sorted and 2_outbox are in 1-to-1 correspondence
"""

import logging
import subprocess
import sys

import check_correspondence
import check_duplicate_sizes
import config
from tasks import purge_weird, sort, upscale


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

    purge_result = purge_weird.run()
    log.info("")

    upscale_result = None
    if sort_result.moved == 0:
        log.info("No new videos moved from inbox. Skipping Stage 3.")
    else:
        upscale_result = upscale.run()
        log.info("")

    duplicate_sizes_result = check_duplicate_sizes.run(show_popup=True)
    log.info("")

    correspondence_result = check_correspondence.run(show_popup=True)

    has_errors = (
        bool(purge_result.missing_sorted)
        or not duplicate_sizes_result.ok
        or not correspondence_result.ok
    )
    if upscale_result is not None:
        has_errors = has_errors or upscale_result.failed > 0

    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()

