from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app_support import funscript

import config
from util import ffprobe, provenance, script_library, sidecar
from util.media_files import library_videos
from util.stage_result import StageResult

log = logging.getLogger(__name__)


@dataclass
class ClipScriptsResult(StageResult):
    written: int = 0
    already_scripted: int = 0
    no_scene_script: int = 0
    no_motion_in_window: int = 0
    unprobeable: int = 0
    unmatched_clip: int = 0


def run() -> ClipScriptsResult:
    result = ClipScriptsResult()

    log.info("=== Stage: scene funscripts -> carved clips ===")
    for video in library_videos(config.VIDEO_LIBRARY_DIR):
        clip = sidecar.read(sidecar.sidecar_path(video)).get("clip")
        if not isinstance(clip, dict):
            continue

        scene, offset = clip.get("full_video"), clip.get("scene_offset")
        if not scene or offset is None:
            result.unmatched_clip += 1
            continue

        destination = script_library.script_path_for_video(video)
        if destination.exists():
            result.already_scripted += 1
            continue

        scene_script = script_library.script_path_for_video(Path(scene))
        if not scene_script.is_file():
            result.no_scene_script += 1
            continue

        clips_own_length = ffprobe.duration_seconds(video)
        if clips_own_length is None:
            result.unprobeable += 1
            log.warning("UNPROBEABLE clip, cannot size its script window: %s", video)
            continue

        trimmed = script_library.trim(funscript.read(scene_script), offset, clips_own_length)
        if _drives_nothing(trimmed):
            result.no_motion_in_window += 1
            log.info("NO MOTION for clip window, leaving unscripted: %s", video)
            continue

        funscript.write(destination, script_library.stamped(trimmed, provenance.CLIP_SCRIPTS))
        result.written += 1
        log.info("TRIM SCRIPT  %s  ->  %s", scene_script, destination)

    log.info(
        "Clip scripts done. Written: %d, Already scripted: %d, Scene unscripted: %d, "
        "No motion in window: %d, Unprobeable: %d, Clip unmatched: %d",
        result.written,
        result.already_scripted,
        result.no_scene_script,
        result.no_motion_in_window,
        result.unprobeable,
        result.unmatched_clip,
    )
    return result


def _drives_nothing(script: dict) -> bool:
    return len(script["actions"]) <= 1
