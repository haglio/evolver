"""Stage 2: Upscale videos from 1_sorted/<source>/<orientation>/ using Topaz."""

import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import config
from util import system_resources
from util.media_files import is_finalized_video_file, iter_finalized_videos, remove_partial_video_files
from util.windows_alert import show_error_window

log = logging.getLogger(__name__)


@dataclass
class UpscaleResult:
    processed: int = 0
    copied_from_legacy: int = 0
    already_done: int = 0
    failed: int = 0
    deferred_low_disk: bool = False
    pending_after_run: int = 0


def run(priority_files: list[Path] | None = None, max_items: int | None = None) -> UpscaleResult:
    result = UpscaleResult()
    max_items = config.UPSCALE_BATCH_LIMIT if max_items is None else max_items
    run_budget_seconds = max(config.UPSCALE_RUN_BUDGET_SECONDS, 0)
    min_start_remaining_seconds = max(config.UPSCALE_MIN_START_REMAINING_SECONDS, 0)
    target_upscaled_dir = _target_upscaled_dir()
    target_weird_dir = _target_weird_dir()
    started_at = time.monotonic()

    # Ensure output dirs exist
    for orient in ("landscape", "portrait"):
        (target_upscaled_dir / orient).mkdir(parents=True, exist_ok=True)
    target_weird_dir.mkdir(parents=True, exist_ok=True)
    removed_partial_outputs = remove_partial_video_files(target_upscaled_dir, config.VIDEO_EXTENSIONS, logger=log)

    log.info("=== Stage 2: upscale from 1_sorted ===")
    log.info("OUT: %s/{landscape,portrait}/<source>/", target_upscaled_dir)
    log.info("Also skip if exists in: %s", target_weird_dir)
    if removed_partial_outputs:
        log.info("Removed %d stale partial output file(s) from %s", removed_partial_outputs, target_upscaled_dir)
    if config.regen_mode_active():
        log.info("Regen mode enabled. Legacy outbox remains at: %s", config.OUTBOX_DIR)

    env = {**os.environ, "TVAI_MODEL_DIR": str(config.TVAI_MODEL_DIR), "TVAI_MODEL_DATA_DIR": str(config.TVAI_MODEL_DIR)}
    candidates = collect_candidates(priority_files=priority_files)
    total_pending = len(candidates)
    if max_items is not None:
        candidates = candidates[:max_items]
    log.info(
        "Queued %d pending video(s); processing up to %d this run (budget %.1f min, keep %.1f min buffer)",
        total_pending,
        len(candidates),
        run_budget_seconds / 60 if run_budget_seconds else 0,
        min_start_remaining_seconds / 60 if min_start_remaining_seconds else 0,
    )

    for in_file, source, orient in candidates:
        elapsed = time.monotonic() - started_at
        remaining_budget = run_budget_seconds - elapsed
        if run_budget_seconds and (result.processed or result.copied_from_legacy or result.failed) and remaining_budget < min_start_remaining_seconds:
            log.info(
                "Stopping Stage 2 before starting another video to stay under the run budget "
                "(elapsed %.1f min, remaining %.1f min).",
                elapsed / 60,
                max(remaining_budget, 0) / 60,
            )
            break

        if _is_low_disk():
            result.deferred_low_disk = True
            result.pending_after_run = total_pending - result.processed - result.copied_from_legacy - result.failed
            _show_low_disk_warning()
            log.warning("Stopping Stage 2 early due to low free disk space.")
            break

        out_dir = target_upscaled_dir / orient / source
        out_dir.mkdir(parents=True, exist_ok=True)
        out_name = f"{in_file.stem}_topaz.mp4"
        out = out_dir / out_name
        tmp = out.with_name(f"{in_file.stem}.partial.{uuid.uuid4().hex}.mp4")

        log.info("Process: %s -> %s  [%s/%s]", in_file.name, out_name, orient, source)

        copy_reason = _copy_legacy_reason(in_file, orient, source, out_name)
        if copy_reason:
            _copy_legacy_counterpart(orient, source, out_name, out)
            result.copied_from_legacy += 1
            log.info("Copied legacy output instead of reprocessing (%s): %s", copy_reason, out)
            _delete_legacy_counterpart(orient, source, out_name)
            continue

        ffmpeg_ok = False
        try:
            ffmpeg_ok = _run_ffmpeg(in_file, tmp, env)
        except OSError:
            log.exception("FAILED (ffmpeg launch error): %s", in_file)

        if ffmpeg_ok:
            if tmp.exists() and tmp.stat().st_size > 0:
                try:
                    tmp.replace(out)
                finally:
                    tmp.unlink(missing_ok=True)
                result.processed += 1
                log.info("Wrote: %s", out)
                _delete_legacy_counterpart(orient, source, out_name)
            else:
                tmp.unlink(missing_ok=True)
                result.failed += 1
                log.info("FAILED (empty output): %s", in_file)
                _record_regen_skip_if_safe(in_file, orient, source, out_name, "empty output")
        else:
            tmp.unlink(missing_ok=True)
            result.failed += 1
            log.info("FAILED (ffmpeg error): %s", in_file)
            _record_regen_skip_if_safe(in_file, orient, source, out_name, "ffmpeg error")

    if not result.deferred_low_disk:
        result.pending_after_run = max(total_pending - result.processed - result.copied_from_legacy - result.failed, 0)

    log.info("")
    log.info("Done.")
    log.info("Upscaled: %d", result.processed)
    log.info("Copied from legacy: %d", result.copied_from_legacy)
    log.info("Skipped (already processed): %d", result.already_done)
    log.info("Failed: %d", result.failed)
    if result.pending_after_run:
        log.info("Pending after this run: %d", result.pending_after_run)
    return result


def has_pending_work(priority_files: list[Path] | None = None) -> bool:
    return bool(collect_candidates(priority_files=priority_files, limit=1))


def collect_candidates(priority_files: list[Path] | None = None, limit: int | None = None) -> list[tuple[Path, str, str]]:
    candidates: list[tuple[Path, str, str]] = []
    seen: set[Path] = set()
    skipped = _load_regen_skip_entries()

    def add_candidate(in_file: Path, source: str, orient: str) -> bool:
        if in_file in seen or not in_file.exists():
            return False
        seen.add(in_file)
        if _is_regen_skipped(in_file, skipped):
            return False
        out_name = f"{in_file.stem}_topaz.mp4"
        if _already_processed(source, out_name):
            return False
        candidates.append((in_file, source, orient))
        return True

    for in_file in priority_files or []:
        try:
            rel = in_file.relative_to(config.SORTED_DIR)
        except ValueError:
            continue
        if len(rel.parts) < 3:
            continue
        source, orient = rel.parts[0], rel.parts[1]
        if orient not in ("landscape", "portrait"):
            continue
        if is_finalized_video_file(in_file, config.VIDEO_EXTENSIONS):
            if add_candidate(in_file, source, orient) and limit is not None and len(candidates) >= limit:
                return candidates

    for source in _iter_sources(config.SORTED_DIR):
        for orient in ("landscape", "portrait"):
            in_root = config.SORTED_DIR / source / orient
            if not in_root.is_dir():
                continue
            for in_file in _iter_videos(in_root):
                if add_candidate(in_file, source, orient) and limit is not None and len(candidates) >= limit:
                    return candidates

    return candidates


def _run_ffmpeg(in_file: Path, tmp: Path, env: dict) -> bool:
    cmd = [
        str(config.FFMPEG),
        "-hide_banner", "-nostdin", "-y",
        "-strict", "2",
        "-hwaccel", "cuda",
        "-i", str(in_file),
        "-sws_flags", "spline+accurate_rnd+full_chroma_int",
        "-filter_complex",
        "tvai_fi=model=apo-8:slowmo=1:fps=60:rdt=0.01:device=0:vram=1:instances=1,"
        "tvai_up=model=gcg-5:scale=4:device=0:vram=1:instances=1",
        "-c:v", "hevc_nvenc",
        "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-b_ref_mode", "disabled",
        "-tag:v", "hvc1",
        "-g", "30",
        "-preset", "p7",
        "-tune", "hq",
        "-rc", "constqp",
        "-qp", "17",
        "-rc-lookahead", "20",
        "-spatial_aq", "1",
        "-aq-strength", "15",
        "-b:v", "0",
        "-an",
        "-map_metadata", "0",
        "-map_metadata:s:v", "0:s:v",
        "-fps_mode:v", "cfr",
        "-movflags", "frag_keyframe+empty_moov+delay_moov+use_metadata_tags+write_colr",
        "-bf", "0",
        "-metadata", f"videoai={config.CURRENT_UPSCALE_VIDEOAI_TAG}",
        "-f", "mp4",
        str(tmp),
    ]
    return subprocess.run(cmd, env=env).returncode == 0


def _already_processed(source: str, fname: str) -> bool:
    target_upscaled_dir = _target_upscaled_dir()
    target_weird_dir = _target_weird_dir()
    for orient in ("landscape", "portrait"):
        p = target_upscaled_dir / orient / source / fname
        if p.exists() and p.stat().st_size > 0:
            return True
    weird = target_weird_dir / fname
    return weird.exists() and weird.stat().st_size > 0


def _legacy_counterpart(orient: str, source: str, out_name: str) -> Path:
    return config.OUT_UPSCALED_DIR / orient / source / out_name


def _copy_legacy_reason(in_file: Path, orient: str, source: str, out_name: str) -> str | None:
    if not config.regen_mode_active():
        return None
    legacy = _legacy_counterpart(orient, source, out_name)
    if not legacy.exists() or legacy.stat().st_size <= 0:
        return None
    if not _has_current_upscale_standard(legacy):
        if not _source_is_preprocessed_and_matches_legacy(in_file, legacy):
            return None
        return "source already appears preprocessed and matches the legacy counterpart"
    return "legacy counterpart already matches the current standard"


def _copy_legacy_counterpart(orient: str, source: str, out_name: str, out: Path) -> None:
    shutil.copy2(_legacy_counterpart(orient, source, out_name), out)


def _has_current_upscale_standard(video_path: Path) -> bool:
    probe = _probe_video(video_path)
    if probe is None:
        return False
    tags = probe.get("format", {}).get("tags", {})
    return tags.get("videoai") == config.CURRENT_UPSCALE_VIDEOAI_TAG


def _source_is_preprocessed_and_matches_legacy(source_path: Path, legacy_path: Path) -> bool:
    source_probe = _probe_video(source_path)
    legacy_probe = _probe_video(legacy_path)
    if source_probe is None or legacy_probe is None:
        return False

    source_tag = source_probe.get("format", {}).get("tags", {}).get("videoai")
    if not source_tag:
        return False
    return _probe_signature(source_probe) == _probe_signature(legacy_probe)


def _probe_video(video_path: Path) -> dict | None:
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(video_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        log.exception("ffprobe failed while checking current-standard metadata: %s", video_path)
        return None

    if probe.returncode != 0:
        log.warning("ffprobe could not inspect metadata for %s", video_path)
        return None

    try:
        raw = json.loads(probe.stdout)
    except json.JSONDecodeError:
        log.warning("ffprobe returned invalid JSON for %s", video_path)
        return None
    return raw


def _probe_signature(probe: dict) -> tuple:
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    tags = fmt.get("tags", {})
    return (
        fmt.get("size"),
        fmt.get("duration"),
        tags.get("videoai"),
        video_stream.get("codec_name"),
        video_stream.get("width"),
        video_stream.get("height"),
        video_stream.get("avg_frame_rate"),
    )


def _target_upscaled_dir() -> Path:
    return config.REGEN_OUT_UPSCALED_DIR if config.regen_mode_active() else config.OUT_UPSCALED_DIR


def _target_weird_dir() -> Path:
    return config.REGEN_WEIRD_DIR if config.regen_mode_active() else config.WEIRD_DIR


def _delete_legacy_counterpart(orient: str, source: str, out_name: str) -> None:
    if not (config.regen_mode_active() and config.DELETE_OLD_OUTBOX_AFTER_REGEN_SUCCESS):
        return
    legacy = _legacy_counterpart(orient, source, out_name)
    if legacy.exists():
        legacy.unlink()
        log.info("Deleted legacy outbox counterpart: %s", legacy)


def _load_regen_skip_entries() -> set[str]:
    if not config.regen_mode_active():
        return set()
    if not config.REGEN_SKIP_FILE.is_file():
        return set()
    return {
        line.strip()
        for line in config.REGEN_SKIP_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _is_regen_skipped(in_file: Path, skipped: set[str]) -> bool:
    if not config.regen_mode_active():
        return False
    try:
        rel = in_file.relative_to(config.SORTED_DIR)
    except ValueError:
        return False
    return rel.as_posix() in skipped


def _record_regen_skip_if_safe(in_file: Path, orient: str, source: str, out_name: str, reason: str) -> None:
    if not config.regen_mode_active():
        return
    legacy = _legacy_counterpart(orient, source, out_name)
    if not legacy.exists() or legacy.stat().st_size <= 0:
        return
    try:
        rel = in_file.relative_to(config.SORTED_DIR).as_posix()
    except ValueError:
        return

    skipped = _load_regen_skip_entries()
    if rel in skipped:
        return

    config.REGEN_SKIP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with config.REGEN_SKIP_FILE.open("a", encoding="utf-8") as fp:
        fp.write(f"{rel}\n")
    log.warning(
        "Recorded regen skip for %s after %s because a legacy outbox counterpart still exists. "
        "This item will no longer be retried every run until you remove it from %s.",
        rel,
        reason,
        config.REGEN_SKIP_FILE,
    )


def _is_low_disk() -> bool:
    free_gb = system_resources.free_bytes(_target_upscaled_dir()) / (1024 ** 3)
    return free_gb < config.LOW_DISK_WARNING_GB


def _show_low_disk_warning() -> None:
    free_gb = system_resources.free_bytes(_target_upscaled_dir()) / (1024 ** 3)
    show_error_window(
        "Evolver - Low Disk Space",
        (
            "Evolver paused Stage 2 because free disk space is below the configured safety floor.\n\n"
            f"Target outbox: {_target_upscaled_dir()}\n"
            f"Free space: {free_gb:.1f} GiB\n"
            f"Required floor: {config.LOW_DISK_WARNING_GB:.1f} GiB\n\n"
            f"Check the log for details:\n{config.LOG_FILE}"
        ),
    )


def _iter_videos(root: Path):
    yield from iter_finalized_videos(root, config.VIDEO_EXTENSIONS)


def _iter_sources(root: Path):
    if not root.is_dir():
        return
    for p in sorted(root.iterdir()):
        if p.is_dir():
            yield p.name
