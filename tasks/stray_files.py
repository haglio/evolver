"""Stage: put right the files in the video tree that are not videos.

Every other stage finds videos by a positive filter — ``suffix.lower() in
VIDEO_EXTENSIONS`` — so a file that fails it is not reported as odd, it is
skipped as though it were not there.  Two things arrive that way and stay
forever: a name whose extension separator is a space or an underscore rather
than a dot (``clip mp4``), which no stage can see is a video at all, and a
``.funscript`` dropped in the video tree instead of the script tree, which the
scripts sync never walks.  This stage repairs the first, sends the second to the
mirror path the scripts sync does walk, and reports anything else by path
without touching it.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import config

log = logging.getLogger(__name__)

# The characters that turn up where the extension's dot belongs.
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


def run() -> StrayFilesResult:
    """Walk the video library, and only it.

    ``VIDEO_LIBRARY_DIR`` covers the inbox, the sorted tree and the outbox,
    which is every folder a video of this library sits in.  The retirement
    archive is deliberately outside it: an archived original is a cold copy that
    has to describe itself, so its sidecar and its funscript sit beside it on
    purpose (see :func:`tasks.nonai_upscale._archive_original`) and are not
    strays.  Walking it would move exactly the files that stage just placed.
    """
    result = StrayFilesResult()
    root = config.VIDEO_LIBRARY_DIR
    if not root.is_dir():
        return result

    log.info("=== Stray files: non-videos in the video tree ===")
    log.info("VIDEOS: %s", root)

    for path in sorted(root.rglob("*")):
        if path.is_file():
            _handle(path, result)

    log.info(
        "Stray files done. Renamed: %d, Rehomed scripts: %d, Reported: %d",
        result.renamed, result.rehomed_scripts, len(result.reported),
    )
    return result


def _handle(path: Path, result: StrayFilesResult) -> None:
    if _is_video(path) or path.name.lower() in _OS_NOISE:
        return

    repaired = _repair_extension(path, result)
    if repaired is None:
        return
    if _is_video(repaired):
        return
    if repaired.suffix.lower() == config.FUNSCRIPT_EXTENSION:
        _rehome_script(repaired, result)
        return
    _report(repaired, result)


def _is_video(path: Path) -> bool:
    """Whether *path* is a video by name — partial outputs included.

    Deliberately looser than :func:`util.media_files.is_finalized_video_file`:
    a ``*.partial.<uuid>.mp4`` is the upscale stage's own in-flight write, so it
    belongs here and is neither a stray nor news.
    """
    return path.suffix.lower() in config.VIDEO_EXTENSIONS


def _repair_extension(path: Path, result: StrayFilesResult) -> Path | None:
    """*path* under its repaired name, itself if nothing to repair, None if blocked."""
    repaired = _repaired_name(path.name)
    if repaired is None:
        return path

    dest = path.with_name(repaired)
    if dest.exists():
        log.warning("MALFORMED NAME (repaired name is taken, leaving it): %s", path)
        _report(path, result)
        return None

    log.info("REPAIR NAME  %s  ->  %s", path.name, dest.name)
    path.rename(dest)
    result.renamed += 1
    return dest


def _repaired_name(name: str) -> str | None:
    """*name* with its extension separator turned back into a dot, or None.

    The token has to be a whole known extension on its own, which is what keeps
    a real title ending in one of these words from being cut into a filename and
    an extension: ``a mp4.txt`` yields the token ``mp4.txt``, not ``mp4``.
    """
    for separator in _EXTENSION_SEPARATORS:
        head, found, token = name.rpartition(separator)
        if not (found and head):
            continue
        if f".{token.lower()}" in _known_extensions():
            return f"{head}.{token}"
    return None


def _known_extensions() -> set[str]:
    """The extensions a repaired name is allowed to end in.

    Read per call rather than folded into a module constant: config is what the
    tests override, and a constant built at import time would answer from the
    values that happened to be loaded first.
    """
    return config.VIDEO_EXTENSIONS | {config.FUNSCRIPT_EXTENSION}


def _rehome_script(path: Path, result: StrayFilesResult) -> None:
    """Move a funscript out of the video tree to its mirror path under the scripts.

    Its home is decided by name, not by folder, and the stage that decides it
    walks only ``SCRIPT_LIBRARY_DIR`` — so the mirror path is where the script
    has to be for anything to look at it at all.  Landing there is not a claim
    that it belongs there: a script naming no video fails the scripts sync and
    raises a popup, which is the point.
    """
    dest = config.SCRIPT_LIBRARY_DIR / path.relative_to(config.VIDEO_LIBRARY_DIR)
    if dest.exists():
        log.warning("STRAY SCRIPT (mirror path is taken, leaving it): %s -> %s", path, dest)
        _report(path, result)
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("REHOME SCRIPT  %s  ->  %s", path, dest)
    path.rename(dest)
    result.rehomed_scripts += 1


def _report(path: Path, result: StrayFilesResult) -> None:
    result.reported.append(str(path.relative_to(config.VIDEO_LIBRARY_DIR)))
