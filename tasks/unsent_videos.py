from __future__ import annotations

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
        result = result + _empty_lane(lane, _names_only_withdrawn_videos_hold(rows, lane))
        result = result + _empty_lane(lane, _soundless_copies_beside_their_sound(rows, lane))

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


def _soundless_copies_beside_their_sound(rows: list[dict], lane: lanes.SentLane) -> set[str]:
    reachable = {origin_stem(video.stem) for video in _videos_under(_reachable_roots(lane))}
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


def _empty_lane(lane: lanes.SentLane, stems: set[str]) -> UnsentVideosResult:
    copies_a_viewer_can_reach, sorted_sources, still_in_the_inbox = _copy_groups(lane, stems)
    result = _delete_all(copies_a_viewer_can_reach)
    if not result.failed:
        result = result + _delete_all(sorted_sources)
    return result + _delete_all(still_in_the_inbox)


def _copy_groups(lane: lanes.SentLane,
                 stems: set[str]) -> tuple[list[Path], list[Path], list[Path]]:
    if not stems:
        return ([], [], [])
    return (_reachable_copies(lane, stems),
            _matches([config.SORTED_DIR / lane.source], stems),
            _matches([config.INBOX_DIR / lane.source], stems))


def _reachable_copies(lane: lanes.SentLane, stems: set[str]) -> list[Path]:
    return _matches(_reachable_roots(lane), stems)


def _reachable_roots(lane: lanes.SentLane) -> list[Path]:
    return [*lane.upscales, lane.trash]


def _matches(roots, stems: set[str]) -> list[Path]:
    return [video for video in _videos_under(roots) if origin_stem(video.stem) in stems]


def _videos_under(roots) -> list[Path]:
    return [video for root in roots if Path(root).is_dir()
            for video in sorted(library_videos(Path(root)))]


def _delete_all(videos: list[Path]) -> UnsentVideosResult:
    result = UnsentVideosResult()
    for video in videos:
        try:
            video.unlink()
        except OSError:
            log.warning("Could not delete %s; leaving it for the next run",
                        video.name, exc_info=True)
            result.failed += 1
            continue
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

