"""Stage: give an unscripted scene the funscript of the clip carved out of it."""

import logging
from dataclasses import dataclass
from pathlib import Path

import config
from util import ffprobe, funscript, sidecar
from util.media_files import library_videos

log = logging.getLogger(__name__)


@dataclass
class SceneScriptsResult:
    written: int = 0
    already_scripted: int = 0
    no_clip_script: int = 0
    scene_gone: int = 0
    unprobeable: int = 0
    unmatched_clip: int = 0


def run() -> SceneScriptsResult:
    """Place each carved clip's funscript where that clip sits in its scene.

    The mirror of :mod:`tasks.clip_scripts`, for the scenes that arrive the
    other way round: a compilation's clips were scripted long before anyone
    scripted the hours they were cut from, so the scene has nothing and the clip
    has the only motion anybody wrote for it. Shifted back to where the clip
    sits, that motion gives the scene a mostly-blank script — silent for the
    length of it, scripted across the stretch the clip covers — which is
    everything of the scene worth driving the device through.

    A scene that has any script of its own is left alone: this is a floor for
    scenes with none, never an edit of somebody's work.
    """
    result = SceneScriptsResult()

    log.info("=== Stage: carved clip funscripts -> their source scenes ===")
    for video in library_videos(config.VIDEO_LIBRARY_DIR):
        clip = sidecar.read(sidecar.sidecar_path(video)).get("clip")
        if not isinstance(clip, dict):
            continue

        # Which scene a clip came from, and where in it, is recorded by the
        # content-matching stage; until that has run there is nothing to place.
        scene, offset = clip.get("full_video"), clip.get("scene_offset")
        if not scene or offset is None:
            result.unmatched_clip += 1
            continue

        scene = Path(scene)
        if not scene.is_file():
            # The match named a file since renamed, moved out or deleted.
            result.scene_gone += 1
            continue

        destination = funscript.script_path_for_video(scene)
        if destination.exists():
            result.already_scripted += 1
            continue

        clip_script = funscript.script_path_for_video(video)
        if not clip_script.is_file():
            result.no_clip_script += 1
            continue

        # The scene's own runtime, not the clip's: what the script covers is the
        # clip's window, but what it is a script *for* is the whole scene.
        duration = ffprobe.duration_seconds(scene)
        if duration is None:
            result.unprobeable += 1
            log.warning("UNPROBEABLE scene, cannot time its script: %s", scene)
            continue

        funscript.write(destination, funscript.place(funscript.read(clip_script), offset, duration))
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
