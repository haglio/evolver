"""Stage 2: Upscale videos from 1_sorted/<source>/<orientation>/ using Topaz."""

import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import config
from util import system_resources
from util.windows_alert import show_error_window

log = logging.getLogger(__name__)


@dataclass
class UpscaleResult:
    processed: int = 0
    already_done: int = 0
    failed: int = 0
    deferred_low_disk: bool = False
    pending_after_run: int = 0


def run(priority_files: list[Path] | None = None, max_items: int | None = None) -> UpscaleResult:
    result = UpscaleResult()
    max_items = config.UPSCALE_BATCH_LIMIT if max_items is None else max_items
    target_upscaled_dir = _target_upscaled_dir()
    target_weird_dir = _target_weird_dir()

    # Ensure output dirs exist
    for orient in ("landscape", "portrait"):
        (target_upscaled_dir / orient).mkdir(parents=True, exist_ok=True)
    target_weird_dir.mkdir(parents=True, exist_ok=True)

    log.info("=== Stage 2: upscale from 1_sorted ===")
    log.info("OUT: %s/{landscape,portrait}/<source>/", target_upscaled_dir)
    log.info("Also skip if exists in: %s", target_weird_dir)
    if config.regen_mode_active():
        log.info("Regen mode enabled. Legacy outbox remains at: %s", config.OUTBOX_DIR)

    env = {**os.environ, "TVAI_MODEL_DIR": str(config.TVAI_MODEL_DIR), "TVAI_MODEL_DATA_DIR": str(config.TVAI_MODEL_DIR)}
    candidates = collect_candidates(priority_files=priority_files)
    total_pending = len(candidates)
    if max_items is not None:
        candidates = candidates[:max_items]
    log.info("Queued %d pending video(s); processing up to %d this run", total_pending, len(candidates))

    for in_file, source, orient in candidates:
        if _is_low_disk():
            result.deferred_low_disk = True
            result.pending_after_run = total_pending - result.processed - result.failed
            _show_low_disk_warning()
            log.warning("Stopping Stage 2 early due to low free disk space.")
            break

        out_dir = target_upscaled_dir / orient / source
        out_dir.mkdir(parents=True, exist_ok=True)
        out_name = f"{in_file.stem}_topaz.mp4"
        out = out_dir / out_name
        tmp = out.with_name(f"{in_file.stem}.partial.{uuid.uuid4().hex}.mp4")

        log.info("Process: %s -> %s  [%s/%s]", in_file.name, out_name, orient, source)

        if _run_ffmpeg(in_file, tmp, env):
            if tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(out)
                result.processed += 1
                log.info("Wrote: %s", out)
                _delete_legacy_counterpart(orient, source, out_name)
            else:
                tmp.unlink(missing_ok=True)
                result.failed += 1
                log.info("FAILED (empty output): %s", in_file)
        else:
            tmp.unlink(missing_ok=True)
            result.failed += 1
            log.info("FAILED (ffmpeg error): %s", in_file)

    if not result.deferred_low_disk:
        result.pending_after_run = max(total_pending - result.processed - result.failed, 0)

    log.info("")
    log.info("Done.")
    log.info("Upscaled: %d", result.processed)
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

    def add_candidate(in_file: Path, source: str, orient: str) -> bool:
        if in_file in seen or not in_file.exists():
            return False
        seen.add(in_file)
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
        if in_file.is_file() and in_file.suffix.lower() in config.VIDEO_EXTENSIONS:
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
        "-metadata", "videoai=Processed using apo-8 for 60 fps interpolation and gcg-5 for 4x upscale",
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


def _target_upscaled_dir() -> Path:
    return config.REGEN_OUT_UPSCALED_DIR if config.regen_mode_active() else config.OUT_UPSCALED_DIR


def _target_weird_dir() -> Path:
    return config.REGEN_WEIRD_DIR if config.regen_mode_active() else config.WEIRD_DIR


def _delete_legacy_counterpart(orient: str, source: str, out_name: str) -> None:
    if not (config.regen_mode_active() and config.DELETE_OLD_OUTBOX_AFTER_REGEN_SUCCESS):
        return
    legacy = config.OUT_UPSCALED_DIR / orient / source / out_name
    if legacy.exists():
        legacy.unlink()
        log.info("Deleted legacy outbox counterpart: %s", legacy)


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
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in config.VIDEO_EXTENSIONS:
            yield p


def _iter_sources(root: Path):
    if not root.is_dir():
        return
    for p in sorted(root.iterdir()):
        if p.is_dir():
            yield p.name
