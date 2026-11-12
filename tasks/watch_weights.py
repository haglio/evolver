from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass
from pathlib import Path

from app_support import video_ids, watch_weights
from app_support.file_channel import write_whole
from app_support.gallery_rows import VideoRows
from app_support.json_store import read_json_or_empty
from app_support.kino_folder import is_ai_video

import config
from tasks.origenerator_commands import GalleryRecords
from util import lanes, origenerator_gallery, sidecar, warm_gun, watch
from util.media_files import path_key, reachable
from util.origenerator_gallery import EVOLVER_UPSCALE, LIBRARY_ID
from util.stage_result import StageResult

log = logging.getLogger(__name__)

_COUNTED_EVENTS = {"completion": "completions", "skip": "skips", "lock": "locks"}
_CURSOR_FIELD = "applied_through"


@dataclass
class WatchWeightsResult(StageResult):
    stamped: int = 0
    favorites_added: int = 0
    favorites_removed: int = 0
    unmapped: int = 0
    write_errors: int = 0
    gallery_untold: bool = False

    @property
    def ok(self) -> bool:
        return not self.write_errors and not self.gallery_untold


@dataclass(frozen=True)
class _PhoneFavorites:
    added: int = 0
    removed: int = 0
    write_errors: int = 0


def run(*, tell_the_gallery: Callable[[], bool] = lambda: True,
        gallery: GalleryRecords | None = None) -> WatchWeightsResult:
    result = _records_brought_up_to_what_was_watched(
        GalleryRecords() if gallery is None else gallery)
    result.gallery_untold = not tell_the_gallery() or result.gallery_untold
    return result


def _records_brought_up_to_what_was_watched(gallery: GalleryRecords) -> WatchWeightsResult:
    result = WatchWeightsResult()
    log.info("=== Stage: watch weights ===")
    outbox = config.WARM_GUN_OUTBOX
    if outbox is not None and not reachable(outbox):
        log.warning("Watch weights and the phone's favorites left as they were: %s cannot be "
                    "reached.", outbox)
        return result
    journals = warm_gun.read_journals(config.WARM_GUN_JOURNAL_DIRS)
    events = sorted({event for found in journals.values() for event in found})
    videos = {event.path: warm_gun.library_video(event.path) for event in events}
    result.unmapped = sum(1 for event in events if videos[event.path] is None)
    phone_favorites = _apply_phone_favorites(journals, videos, gallery)
    result.favorites_added = phone_favorites.added
    result.favorites_removed = phone_favorites.removed
    result.write_errors = phone_favorites.write_errors
    phone_counts = _phone_counts(events, videos)
    fun_time_counts = read_json_or_empty(config.FUN_TIME_WATCH_STATS_FILE)
    played = list(_played_videos())
    ai_videos = [video for video in played if is_ai_video(video)]
    if ai_videos:
        handed = gallery.watched(_ai_totals(ai_videos, fun_time_counts, phone_counts))
        result.stamped += 0 if handed is None else handed.done
        result.gallery_untold = handed is None
    for video in played:
        if is_ai_video(video):
            continue
        key = path_key(video)

        def stamp_the_watching(payload: dict, key=key) -> dict | None:
            fun_times = fun_time_counts.get(video_ids.recorded_id(payload), fun_time_counts.get(key))
            stamped = watch.stamped(payload, watch_weights.add_counts(fun_times, phone_counts.get(key)))
            return stamped if stamped != payload else None

        if sidecar.update(sidecar.sidecar_path(video), stamp_the_watching) is not None:
            result.stamped += 1
    log.info(
        "Watch weights: stamped %d record(s); phone favorites added %d, removed %d; "
        "%d journal line(s) named no video here.",
        result.stamped, result.favorites_added, result.favorites_removed, result.unmapped,
    )
    return result


def _ai_totals(videos: list[Path], fun_time_counts: dict,
               phone_counts: dict[str, dict[str, int]]) -> dict[Path, dict[str, int]]:
    library_id_of = _library_ids()

    def counted_under(key: str | None) -> dict | None:
        return None if key is None else fun_time_counts.get(key)

    return {video: watch_weights.add_counts(counted_under(library_id_of(video)),
                                            counted_under(path_key(video)),
                                            phone_counts.get(path_key(video)))
            for video in videos if video.is_file()}


def _library_ids() -> Callable[[Path], str | None]:
    try:
        rows = origenerator_gallery.rows(("prompt_id", "output_files"),
                                         optional=(EVOLVER_UPSCALE, LIBRARY_ID))
    except (FileNotFoundError, sqlite3.Error):
        log.warning("Could not read Origenerator's gallery; Fun Time's counts kept under an "
                    "AI video's old record id are not added this run.", exc_info=True)
        return lambda _video: None
    row_of, by_id = VideoRows(rows), {row["prompt_id"]: row for row in rows}
    return lambda video: (by_id.get(row_of(video)) or {}).get(LIBRARY_ID)


def _played_videos() -> Iterator[Path]:
    for clip in lanes.ai_videos():
        yield clip.upscale
    yield from lanes.genau_flicks()
    yield from lanes.non_ai_videos()


def _phone_counts(
    events: list[warm_gun.Event], videos: dict[str, Path | None]
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(watch_weights.COUNT_FIELDS, 0))
    for event in events:
        video, field = videos[event.path], _COUNTED_EVENTS.get(event.event)
        if video is not None and field is not None:
            counts[path_key(video)][field] += 1
    return counts


def _apply_phone_favorites(
    journals: dict[str, list[warm_gun.Event]], videos: dict[str, Path | None],
    gallery: GalleryRecords,
) -> _PhoneFavorites:
    carried = {True: 0, False: 0}

    def carry(event: warm_gun.Event) -> bool:
        video = videos[event.path]
        if video is not None and video.exists() and is_ai_video(video):
            favorite = warm_gun.FAVORITE_EVENTS[event.event]
            handed = gallery.favorite(video, favorite)
            if handed is None:
                log.info("Phone %s of %s waits for Origenerator's gallery to take it.",
                         event.event, video)
                return False
            carried[favorite] += handed.done
        elif video is not None and video.exists():
            favorite = warm_gun.FAVORITE_EVENTS[event.event]
            carried[favorite] += sidecar.mark_favorite(video, favorite)
        elif video is not None and warm_gun.played_video(event.path).exists():
            log.info("Phone %s of %s waits for its upscale.", event.event, video)
            return False
        return True

    try:
        _applied_once(journals, config.WARM_GUN_FAVORITES_CURSOR_FILE, warm_gun.FAVORITE_EVENTS,
                      carry)
    except OSError:
        log.exception("Could not mark the phone's favorites")
        return _PhoneFavorites(carried[True], carried[False], 1)
    return _PhoneFavorites(carried[True], carried[False])


def _applied_once(
    journals: dict[str, list[warm_gun.Event]], cursor_file: Path, kinds: Collection[str],
    apply: Callable[[warm_gun.Event], bool],
) -> None:
    cursors = _cursors(cursor_file)
    applied = dict(cursors)
    try:
        for name, events in journals.items():
            for event in events:
                if event.event not in kinds or event.t <= cursors.get(name, -1):
                    continue
                if not apply(event):
                    break
                applied[name] = event.t
    finally:
        if applied != cursors:
            write_whole(cursor_file, json.dumps({_CURSOR_FIELD: applied}))


def _cursors(cursor_file: Path) -> dict[str, int]:
    stored = read_json_or_empty(cursor_file).get(_CURSOR_FIELD)
    if isinstance(stored, dict):
        return {name: int(t) for name, t in stored.items()}
    if isinstance(stored, int | float) and not isinstance(stored, bool):
        return {warm_gun.PHONE_JOURNAL: int(stored)}
    return {}
