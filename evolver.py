#!/usr/bin/env python3
"""evolver.py - video collection maintenance pipeline.

Runs on a 15-minute Task Scheduler trigger. Stages:
  1. sort    - move new videos from inbox into sorted folders by source/orientation
  2. purge   - remove weird outputs and their matching sources
  3. scripts - align funscripts to mirror the video library tree
  3.5.bookmarks - sync Fun Time favorites into a Chrome bookmarks folder
  4. prompts - scrape AI prompt metadata into mirrored JSON files
  5. upscale - apply Topaz frame interpolation + 4x upscale to sorted videos
  6. dupes   - scan 1_sorted for likely duplicate videos by exact filesize
  7. verify  - check 1_sorted and 2_outbox are in 1-to-1 correspondence
"""

import logging
import json
import subprocess
import sys
from pathlib import Path

import check_correspondence
import check_duplicate_sizes
import config
from tasks import bookmarks_sync, prompt_scrape, purge_weird, scripts_sync, sort, upscale
from util.media_files import iter_finalized_videos
from util import system_resources
from util.windows_alert import show_info_window


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
    if not upscale.has_pending_work(priority_files=priority_files):
        log.info("No pending Stage 5 work found. Skipping upscale.")
    elif _should_skip_upscale_due_to_cpu(log):
        log.info("Skipping Stage 5 because CPU usage is above the configured threshold.")
    else:
        upscale_result = upscale.run(priority_files=priority_files, max_items=config.UPSCALE_BATCH_LIMIT)
        log.info("")

    duplicate_sizes_result = check_duplicate_sizes.run(show_popup=True)
    log.info("")

    correspondence_result = check_correspondence.run(show_popup=True)
    _finish_regen_if_complete(log, correspondence_result)

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
        log.exception("CPU usage probe failed; proceeding with Stage 5.")
        return False

    log.info(
        "CPU busy sample: %.1f%% (threshold %.1f%%)",
        busy_percent,
        config.CPU_BUSY_SKIP_THRESHOLD_PCT,
    )
    return busy_percent >= config.CPU_BUSY_SKIP_THRESHOLD_PCT


def _finish_regen_if_complete(log: logging.Logger, correspondence_result) -> bool:
    if not (config.regen_mode_active() and config.AUTO_CUTOVER_ON_REGEN_COMPLETE):
        return False
    if not correspondence_result.ok:
        return False
    if _dir_has_video_files(config.OUTBOX_DIR):
        return False

    log.info("Regeneration complete. Starting final outbox cutover.")
    _remove_empty_dirs(config.OUTBOX_DIR)
    if config.OUTBOX_DIR.exists():
        remaining = list(config.OUTBOX_DIR.iterdir())
        if remaining:
            names = ", ".join(p.name for p in remaining[:10])
            raise RuntimeError(f"Cannot cut over regen output; legacy outbox still contains: {names}")
        config.OUTBOX_DIR.rmdir()

    config.REGEN_OUTBOX_DIR.rename(config.OUTBOX_DIR)
    _simplify_fun_time_config(log)
    config.REGEN_COMPLETE_MARKER.write_text("complete\n", encoding="utf-8")
    _write_post_regen_cleanup_note(log)
    log.info("Final regen cutover complete. %s is now the live outbox again.", config.OUTBOX_DIR)
    show_info_window(
        "Evolver - Regeneration Complete",
        (
            "Evolver finished regenerating the active outbox.\n\n"
            f"Cutover complete: {config.REGEN_OUTBOX_DIR.name} was renamed back to {config.OUTBOX_DIR.name}.\n"
            f"Completion marker: {config.REGEN_COMPLETE_MARKER}\n\n"
            "Future runs will use 2_outbox normally unless you clear the completion marker and start another regeneration.\n\n"
            "Manual review recommended: check the current config/state and decide whether you want to set REGEN_ENABLED back to False and remove dormant regen-only cleanup paths."
        ),
    )
    return True


def _dir_has_video_files(root: Path) -> bool:
    if not root.is_dir():
        return False
    return any(iter_finalized_videos(root, config.VIDEO_EXTENSIONS))


def _remove_empty_dirs(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


def _simplify_fun_time_config(log: logging.Logger) -> None:
    path = config.FUN_TIME_CONFIG_FILE
    if not path.is_file():
        log.warning("Fun Time config not found during regen cutover: %s", path)
        return

    with path.open("r", encoding="utf-8") as fp:
        raw = json.load(fp)

    paths = raw.get("paths")
    if not isinstance(paths, dict):
        raise RuntimeError(f"Fun Time config has invalid paths section: {path}")

    paths["portrait_dirs"] = [str(config.OUT_UPSCALED_DIR / "portrait").replace("\\", "/")]
    paths["landscape_dirs"] = [str(config.OUT_UPSCALED_DIR / "landscape").replace("\\", "/")]

    with path.open("w", encoding="utf-8", newline="\n") as fp:
        json.dump(raw, fp, indent=2)
        fp.write("\n")
    log.info("Simplified Fun Time config back to single live outbox folders: %s", path)


def _write_post_regen_cleanup_note(log: logging.Logger) -> None:
    note = (
        "# Post-Regen Cleanup\n\n"
        "The one-time 2_outbox -> 3_new_outbox regeneration has completed.\n\n"
        "Operational cutover is already finished:\n"
        "- 3_new_outbox was renamed back to 2_outbox.\n"
        "- Fun Time was simplified back to single live 2_outbox folders.\n"
        "- Evolver wrote the regen completion marker.\n\n"
        "Optional cleanup for a future maintenance pass:\n"
        "- set REGEN_ENABLED back to False in config.py\n"
        "- remove the regen completion marker file if you no longer want it\n"
        "- remove dormant regen-specific code/config paths if you are confident this migration will never be repeated\n"
    )
    config.POST_REGEN_CLEANUP_NOTE.write_text(note, encoding="utf-8")
    log.info("Wrote post-regen cleanup note: %s", config.POST_REGEN_CLEANUP_NOTE)


if __name__ == "__main__":
    main()
