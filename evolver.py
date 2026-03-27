#!/usr/bin/env python3
"""evolver.py - video collection maintenance pipeline.

Runs on a 15-minute Task Scheduler trigger. Stages:
  1. sort       - move new videos from inbox into sorted folders by source/orientation
  2. purge      - remove weird outputs and their matching sources
  3. scripts    - align funscripts to mirror the video library tree
  4. bookmarks  - sync Fun Time favorites into a Chrome bookmarks folder
  5. prompts    - scrape AI prompt metadata into mirrored JSON files
  6. upscale    - apply Topaz frame interpolation + 4x upscale to sorted videos
  7. dupes      - scan non_AI for likely duplicate videos by exact filesize
  8. verify     - check 1_sorted and 2_outbox are in 1-to-1 correspondence
"""

import logging
import subprocess
import sys

import check_correspondence
import check_duplicate_sizes
import config
from tasks import bookmarks_sync, prompt_scrape, purge_weird, scripts_sync, sort, upscale
from util import system_resources


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

    scripts_sync_result = scripts_sync.run(show_popup=True)
    log.info("")

    bookmarks_sync_result = bookmarks_sync.run()
    log.info("")

    prompt_scrape_result = prompt_scrape.run()
    log.info("")

    priority_files = getattr(sort_result, "moved_files", [])
    upscale_result = None
    upscale_skipped = False
    if not upscale.has_pending_work(priority_files=priority_files):
        log.info("No pending upscale work found. Skipping upscale.")
    elif _should_skip_upscale_due_to_cpu(log):
        log.info("Skipping upscale because CPU usage is above the configured threshold.")
        upscale_skipped = True
    else:
        upscale_result = upscale.run(priority_files=priority_files, max_items=config.UPSCALE_BATCH_LIMIT)
        log.info("")

    duplicate_sizes_result = check_duplicate_sizes.run(show_popup=True)
    log.info("")

    upscale_still_pending = (
        upscale_skipped
        or (upscale_result is not None and upscale_result.pending_after_run > 0)
    )
    if upscale_still_pending:
        log.info("Skipping correspondence check: upscale has unprocessed files that would cause a false mismatch.")
        correspondence_result = check_correspondence.CorrespondenceResult(sorted_count=0, outbox_count=0)
    else:
        correspondence_result = check_correspondence.run(show_popup=True)

    has_errors = (
        bool(purge_result.missing_sorted)
        or not scripts_sync_result.ok
        or not bookmarks_sync_result.ok
        or not prompt_scrape_result.ok
        or not duplicate_sizes_result.ok
        or not correspondence_result.ok
    )
    if upscale_result is not None:
        has_errors = has_errors or upscale_result.failed > 0 or upscale_result.deferred_low_disk

    sys.exit(1 if has_errors else 0)


def _should_skip_upscale_due_to_cpu(log: logging.Logger) -> bool:
    if not config.ENABLE_CPU_BUSY_SKIP:
        return False
    try:
        busy_percent = system_resources.cpu_busy_percent(config.CPU_BUSY_SKIP_SAMPLE_SECONDS)
    except Exception:
        log.exception("CPU usage probe failed; proceeding with Stage 6.")
        return False

    log.info(
        "CPU busy sample: %.1f%% (threshold %.1f%%)",
        busy_percent,
        config.CPU_BUSY_SKIP_THRESHOLD_PCT,
    )
    return busy_percent >= config.CPU_BUSY_SKIP_THRESHOLD_PCT




if __name__ == "__main__":
    main()
