"""Stage: give a carved clip the part of its source scene's funscript it was cut from."""

import logging
from dataclasses import dataclass
from pathlib import Path

import config
from util import ffprobe, funscript, sidecar
from util.media_files import library_videos

log = logging.getLogger(__name__)


@dataclass
class ClipScriptsResult:
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

        # Which scene a clip came from, and where in it, is recorded by the
        # content-matching stage; until that has run there is nothing to cut.
        scene, offset = clip.get("full_video"), clip.get("scene_offset")
        if not scene or offset is None:
            result.unmatched_clip += 1
            continue

        destination = funscript.script_path_for_video(video)
        if destination.exists():
            result.already_scripted += 1
            continue

        scene_script = funscript.script_path_for_video(Path(scene))
        if not scene_script.is_file():
            result.no_scene_script += 1
            continue

        # The clip may be a re-encode of the scene at another frame rate, so how
        # far its window reaches is the clip's own business, not arithmetic on
        # the scene's timeline.
        duration = ffprobe.duration_seconds(video)
        if duration is None:
            result.unprobeable += 1
            log.warning("UNPROBEABLE clip, cannot size its script window: %s", video)
            continue

        trimmed = funscript.trim(funscript.read(scene_script), offset, duration)
        # One action is a position the device holds, not a stroke: a script of
        # it would drive nothing, and having one stops anybody scripting the
        # clip properly later.
        if len(trimmed["actions"]) < 2:
            result.no_motion_in_window += 1
            log.info("NO MOTION for clip window, leaving unscripted: %s", video)
            continue

        funscript.write(destination, trimmed)
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
