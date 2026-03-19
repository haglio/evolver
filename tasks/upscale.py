"""Stage 2: Upscale videos from 1_sorted/<source>/<orientation>/ using Topaz."""

import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import config

log = logging.getLogger(__name__)


@dataclass
class UpscaleResult:
    processed: int = 0
    already_done: int = 0
    failed: int = 0


def run() -> UpscaleResult:
    result = UpscaleResult()

    # Ensure output dirs exist
    for orient in ("landscape", "portrait"):
        (config.OUT_UPSCALED_DIR / orient).mkdir(parents=True, exist_ok=True)
    config.WEIRD_DIR.mkdir(parents=True, exist_ok=True)

    log.info("=== Stage 2: upscale from 1_sorted ===")
    log.info("OUT: %s/{landscape,portrait}/<source>/", config.OUT_UPSCALED_DIR)
    log.info("Also skip if exists in: %s", config.WEIRD_DIR)

    env = {**os.environ, "TVAI_MODEL_DIR": str(config.TVAI_MODEL_DIR), "TVAI_MODEL_DATA_DIR": str(config.TVAI_MODEL_DIR)}

    for source in _iter_sources(config.SORTED_DIR):
        for orient in ("landscape", "portrait"):
            in_root = config.SORTED_DIR / source / orient
            if not in_root.is_dir():
                continue

            out_dir = config.OUT_UPSCALED_DIR / orient / source
            out_dir.mkdir(parents=True, exist_ok=True)

            log.info("--- Upscaling: %s / %s ---", source, orient)

            for in_file in _iter_videos(in_root):
                out_name = f"{in_file.stem}_topaz.mp4"

                if _already_processed(source, out_name):
                    log.info("Skip (already processed): %s/%s", source, out_name)
                    result.already_done += 1
                    continue

                out = out_dir / out_name
                tmp = out.with_name(f"{in_file.stem}.partial.{uuid.uuid4().hex}.mp4")

                log.info("Process: %s -> %s  [%s/%s]", in_file.name, out_name, orient, source)

                if _run_ffmpeg(in_file, tmp, env):
                    if tmp.exists() and tmp.stat().st_size > 0:
                        tmp.replace(out)
                        result.processed += 1
                        log.info("Wrote: %s", out)
                    else:
                        tmp.unlink(missing_ok=True)
                        result.failed += 1
                        log.info("FAILED (empty output): %s", in_file)
                else:
                    tmp.unlink(missing_ok=True)
                    result.failed += 1
                    log.info("FAILED (ffmpeg error): %s", in_file)

    log.info("")
    log.info("Done.")
    log.info("Upscaled: %d", result.processed)
    log.info("Skipped (already processed): %d", result.already_done)
    log.info("Failed: %d", result.failed)
    return result


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
    for orient in ("landscape", "portrait"):
        p = config.OUT_UPSCALED_DIR / orient / source / fname
        if p.exists() and p.stat().st_size > 0:
            return True
    weird = config.WEIRD_DIR / fname
    return weird.exists() and weird.stat().st_size > 0


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
