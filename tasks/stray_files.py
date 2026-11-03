from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import config
from util import lanes, script_library
from util.media_files import is_partial_path, library_files

log = logging.getLogger(__name__)

_EXTENSION_SEPARATORS = (" ", "_", "-")

# Files Windows writes into a folder by itself.  They are not strays to fix and
# not news to report: reporting them would put every library folder on a list
# that never empties, which is how a report stops being read.
_OS_NOISE = frozenset({"desktop.ini", "thumbs.db", ".ds_store"})


@dataclass
class StrayFilesResult:
    renamed: int = 0
    rehomed_scripts: int = 0
    reported: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.reported


@dataclass(frozen=True)
class _Handled:
    renamed: bool = False
    rehomed: bool = False
    reported: str = ""


def run() -> StrayFilesResult:
    result = StrayFilesResult()
    root = config.VIDEO_LIBRARY_DIR
    if not root.is_dir():
        return result

    log.info("=== Stray files: non-videos in the video tree ===")
    log.info("VIDEOS: %s", root)

    for path in sorted(library_files(root)):
        handled = _handle(path)
        if handled.renamed:
            result.renamed += 1
        if handled.rehomed:
            result.rehomed_scripts += 1
        if handled.reported:
            result.reported.append(handled.reported)

    log.info(
        "Stray files done. Renamed: %d, Rehomed scripts: %d, Reported: %d",
        result.renamed, result.rehomed_scripts, len(result.reported),
    )
    return result


def _handle(path: Path) -> _Handled:
    if _is_video(path) or is_partial_path(path) or path.name.lower() in _OS_NOISE:
        return _Handled()

    repaired, renamed = _repair_extension(path)
    if repaired is None:
        return _Handled(reported=_reportable(path))
    if _is_video(repaired):
        return _Handled(renamed=renamed)
    if repaired.suffix.lower() == config.FUNSCRIPT_EXTENSION:
        blocked = _rehome_script(repaired)
        return _Handled(renamed=renamed, rehomed=not blocked, reported=blocked)
    return _Handled(renamed=renamed, reported=_reportable(repaired))


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in config.VIDEO_EXTENSIONS


def _repair_extension(path: Path) -> tuple[Path | None, bool]:
    repaired = _repaired_name(path.name)
    if repaired is None:
        return path, False

    dest = path.with_name(repaired)
    if dest.exists():
        log.warning("MALFORMED NAME (repaired name is taken, leaving it): %s", path)
        return None, False

    log.info("REPAIR NAME  %s  ->  %s", path.name, dest.name)
    path.rename(dest)
    return dest, True


def _repaired_name(name: str) -> str | None:
    for separator in _EXTENSION_SEPARATORS:
        head, found, token = name.rpartition(separator)
        if not (found and head):
            continue
        if f".{token.lower()}" in _known_extensions():
            return f"{head}.{token}"
    return None


def _known_extensions() -> set[str]:
    return config.VIDEO_EXTENSIONS | {config.FUNSCRIPT_EXTENSION}


def _rehome_script(path: Path) -> str:
    dest = config.SCRIPT_LIBRARY_DIR / path.relative_to(config.VIDEO_LIBRARY_DIR)
    if dest.exists():
        log.warning("STRAY SCRIPT (mirror path is taken, leaving it): %s -> %s", path, dest)
        return _reportable(path)

    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("REHOME SCRIPT  %s  ->  %s", path, dest)
    path.rename(dest)
    if _handed_over_by_origenerator(path):
        script_library.mark_generated(dest)
    return ""


def _handed_over_by_origenerator(path: Path) -> bool:
    return path.is_relative_to(config.INBOX_DIR / lanes.ORIGENERATOR_SOURCE)


def _reportable(path: Path) -> str:
    return str(path.relative_to(config.VIDEO_LIBRARY_DIR))
