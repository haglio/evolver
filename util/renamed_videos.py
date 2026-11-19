from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

from util import script_library, sidecar
from util.media_files import is_finalized_video_file
from util.video_kind import duration_of

Duration = Callable[[Path], float | None]

SAME_DURATION_SECONDS = 1e-3


def renamed_in_place(script: Path, folder: Path, duration: Duration) -> tuple[Path, Path] | None:
    if not folder.is_dir():
        return None
    unscripted = [video for video in sorted(folder.iterdir())
                  if is_finalized_video_file(video) and not _has_a_script(video)]
    if not unscripted:
        return None
    was_at = unscripted[0].with_stem(script.stem)
    if script_library.script_path_for_video(was_at) != script:
        return None
    seconds = duration_of(sidecar.read(sidecar.sidecar_path(was_at)))
    if seconds is None:
        return None
    matches = [video for video in unscripted if _runs_for(video, seconds, duration)]
    return (was_at, matches[0]) if len(matches) == 1 else None


def _has_a_script(video: Path) -> bool:
    try:
        return script_library.script_path_for_video(video).exists()
    except ValueError:
        return True


def _runs_for(video: Path, seconds: float, duration: Duration) -> bool:
    measured = duration(video)
    return measured is not None and math.isclose(measured, seconds, abs_tol=SAME_DURATION_SECONDS)
