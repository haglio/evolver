"""Stage: align .funscript files to mirror the video library tree."""

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import config
from util.windows_alert import show_error_window

log = logging.getLogger(__name__)


@dataclass
class ScriptsSyncResult:
    moved: int = 0
    already_aligned: int = 0
    unmatched: int = 0
    ambiguous: int = 0
    collisions: int = 0

    @property
    def ok(self) -> bool:
        return not (self.unmatched or self.ambiguous or self.collisions)


def run(show_popup: bool = False) -> ScriptsSyncResult:
    result = ScriptsSyncResult()
    config.SCRIPT_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)

    log.info("=== Stage 3: scripts -> mirror video library ===")
    log.info("VIDEOS:  %s", config.VIDEO_LIBRARY_DIR)
    log.info("SCRIPTS: %s", config.SCRIPT_LIBRARY_DIR)

    video_index = _index_videos(config.VIDEO_LIBRARY_DIR)

    for script_path in _iter_funscripts(config.SCRIPT_LIBRARY_DIR):
        matches = video_index.get(script_path.stem, [])
        if not matches:
            log.info("UNMATCHED script (no video basename match): %s", script_path)
            result.unmatched += 1
            continue
        if len(matches) > 1:
            log.warning("AMBIGUOUS script match for %s: %s", script_path, ", ".join(str(p) for p in matches))
            result.ambiguous += 1
            continue

        dest = _script_path_for_video(matches[0])
        if script_path == dest:
            result.already_aligned += 1
            continue
        if dest.exists():
            log.warning("SCRIPT COLLISION (destination exists, leaving source in place): %s -> %s", script_path, dest)
            result.collisions += 1
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        log.info("MOVE SCRIPT  %s  ->  %s", script_path, dest)
        script_path.rename(dest)
        result.moved += 1

    _remove_empty_dirs(config.SCRIPT_LIBRARY_DIR)
    log.info(
        "Stage 3 done. Moved: %d, Already aligned: %d, Unmatched: %d, Ambiguous: %d, Collisions: %d",
        result.moved,
        result.already_aligned,
        result.unmatched,
        result.ambiguous,
        result.collisions,
    )
    if not result.ok:
        log.error("Stage 3 failed. See log entries above for unresolved funscript alignment issues.")
        if show_popup:
            log.info("Showing error popup for scripts-sync failure")
            show_error_window("Evolver - Funscript Match Error", _popup_message(result))
            log.info("Error popup dismissed")
    return result


def _index_videos(root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    if not root.is_dir():
        return index
    for video_path in root.rglob("*"):
        if video_path.is_file() and video_path.suffix.lower() in config.VIDEO_EXTENSIONS:
            index[video_path.stem].append(video_path)
    return index


def _iter_funscripts(root: Path):
    for path in root.rglob(f"*{config.FUNSCRIPT_EXTENSION}"):
        if path.is_file():
            yield path


def _script_path_for_video(video_path: Path) -> Path:
    rel = video_path.relative_to(config.VIDEO_LIBRARY_DIR)
    return (config.SCRIPT_LIBRARY_DIR / rel).with_suffix(config.FUNSCRIPT_EXTENSION)


def _remove_empty_dirs(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass


def _popup_message(result: ScriptsSyncResult) -> str:
    lines = [
        "Evolver found funscript files that do not cleanly match the video library.",
        "",
        "Check the log for full details:",
        str(config.LOG_FILE),
        "",
        f"Unmatched funscripts: {result.unmatched}",
        f"Ambiguous basename matches: {result.ambiguous}",
        f"Destination collisions: {result.collisions}",
    ]
    return "\n".join(lines)
