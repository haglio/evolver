from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from pathlib import Path

from app_support.gallery_rows import is_video_name, output_entries
from app_support.video_names import origin_stem

import config
from util import lanes, origenerator_gallery, script_library
from util.media_files import library_videos
from util.stage_result import StageResult

log = logging.getLogger(__name__)


@dataclass
class UnsentVideosResult(StageResult):
    deleted: int = 0
    deleted_scripts: int = 0
    failed: int = 0

    @property
    def ok(self) -> bool:
        return not self.failed

    def __add__(self, other: UnsentVideosResult) -> UnsentVideosResult:
        return UnsentVideosResult(
            deleted=self.deleted + other.deleted,
            deleted_scripts=self.deleted_scripts + other.deleted_scripts,
            failed=self.failed + other.failed)


def run() -> UnsentVideosResult:
    result = UnsentVideosResult()
    try:
        rows = _gallery_rows()
    except FileNotFoundError:
        return result

    log.info("=== Stage: videos unsent in Origenerator ===")
    for lane in lanes.sent_lanes():
        files = _LaneFiles(lane)
        result = result + files.emptied_of(_names_only_withdrawn_videos_hold(rows, lane))
        result = result + files.emptied_of(_soundless_copies_beside_their_sound(rows, files.reachable))

    log.info("Withdrawn done. Deleted: %d, failed: %d", result.deleted, result.failed)
    return result


SILENT_COPY_ROLE = "silent"

COLUMNS = ("output_files",)


def _gallery_rows() -> list[dict]:
    return origenerator_gallery.rows(
        COLUMNS,
        optional=tuple(column for lane in lanes.sent_lanes() for column in lane.stamps),
    )


def _names_only_withdrawn_videos_hold(rows: list[dict], lane: lanes.SentLane) -> set[str]:
    withdrawn = origenerator_gallery.video_stems(rows, lambda row: row.get(lane.unsent_column))
    return withdrawn - origenerator_gallery.video_stems(rows, lane.still_sent)


def _soundless_copies_beside_their_sound(rows: list[dict], reachable_copies: list[Path]) -> set[str]:
    reachable = {origin_stem(video.stem) for video in reachable_copies}
    stems = set()
    for row in rows:
        videos = [entry for entry in output_entries(row) or []
                  if is_video_name(entry["filename"])]
        soundless = {Path(entry["filename"]).stem for entry in videos
                     if entry.get("role") == SILENT_COPY_ROLE}
        with_sound = {Path(entry["filename"]).stem for entry in videos} - soundless
        if with_sound & reachable:
            stems |= soundless
    return stems


class _LaneFiles:
    def __init__(self, lane: lanes.SentLane) -> None:
        self._lane = lane

    @functools.cached_property
    def reachable(self) -> list[Path]:
        return _videos_under([*self._lane.upscales, self._lane.trash])

    @functools.cached_property
    def sorted_sources(self) -> list[Path]:
        return _videos_under([config.SORTED_DIR / self._lane.source])

    @functools.cached_property
    def still_in_the_inbox(self) -> list[Path]:
        return _videos_under([config.INBOX_DIR / self._lane.source])

    def emptied_of(self, stems: set[str]) -> UnsentVideosResult:
        if not stems:
            return UnsentVideosResult()
        result = _delete_all(self.reachable, stems)
        if not result.failed:
            result = result + _delete_all(self.sorted_sources, stems)
        return result + _delete_all(self.still_in_the_inbox, stems)


def _videos_under(roots) -> list[Path]:
    return [video for root in roots if Path(root).is_dir()
            for video in sorted(library_videos(Path(root)))]


def _delete_all(videos: list[Path], stems: set[str]) -> UnsentVideosResult:
    result = UnsentVideosResult()
    for video in [video for video in videos if origin_stem(video.stem) in stems]:
        try:
            video.unlink()
        except OSError:
            log.warning("Could not delete %s; leaving it for the next run",
                        video.name, exc_info=True)
            result.failed += 1
            continue
        videos.remove(video)
        log.info("WITHDRAWN %s", video)
        result.deleted += 1
        result = result + _delete_scripts(video)
    return result


def _delete_scripts(video: Path) -> UnsentVideosResult:
    result = UnsentVideosResult()
    for script in script_library.scripts_held_for(video, lanes.upscale_filed_for(video)):
        try:
            script_library.delete_script(script)
        except OSError:
            log.warning("Could not delete %s; leaving it for the next run",
                        script.name, exc_info=True)
            result.failed += 1
            continue
        log.info("Deleted funscript: %s", script)
        result.deleted_scripts += 1
    return result

