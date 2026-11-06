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
class SceneScriptsResult(StageResult):
    written: int = 0
    already_scripted: int = 0
    no_clip_script: int = 0
    scene_gone: int = 0
    unprobeable: int = 0
    unmatched_clip: int = 0


def run() -> SceneScriptsResult:
    result = SceneScriptsResult()

    log.info("=== Stage: carved clip funscripts -> their source scenes ===")
    for video in library_videos(config.VIDEO_LIBRARY_DIR):
        clip = sidecar.read(sidecar.sidecar_path(video)).get("clip")
        if not isinstance(clip, dict):
            continue

        scene, offset = clip.get("full_video"), clip.get("scene_offset")
        if not scene or offset is None:
            result.unmatched_clip += 1
            continue

        scene = Path(scene)
        if not scene.is_file():
            result.scene_gone += 1
            continue

        destination = script_library.script_path_for_video(scene)
        if destination.exists():
            result.already_scripted += 1
            continue

        clip_script = script_library.script_path_for_video(video)
        if not clip_script.is_file():
            result.no_clip_script += 1
            continue

        duration = ffprobe.duration_seconds(scene)
        if duration is None:
            result.unprobeable += 1
            log.warning("UNPROBEABLE scene, cannot time its script: %s", scene)
            continue

        placed = script_library.place(funscript.read(clip_script), offset, duration)
        funscript.write(destination, script_library.stamped(placed, provenance.SCENE_SCRIPTS))
        result.written += 1
        log.info("PLACE SCRIPT  %s  ->  %s", clip_script, destination)

    log.info(
        "Scene scripts done. Written: %d, Already scripted: %d, Clip unscripted: %d, "
        "Scene gone: %d, Unprobeable: %d, Clip unmatched: %d",
        result.written,
        result.already_scripted,
        result.no_clip_script,
        result.scene_gone,
        result.unprobeable,
        result.unmatched_clip,
    )
    return result
