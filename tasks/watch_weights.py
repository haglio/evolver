"""Stage: every app's viewing of a video summed on its sidecar as one weight,
and favorites carried both ways.

Fun Time's counts come from its own stats file, the phone's from Warm Gun's
journal, which reaches this machine inside the synced library.  The sum and
its weight go on the sidecar (``util.watch``), where Fun Time and Warm Gun
read one number instead of each keeping a formula.  A favorite made on the
phone goes into Fun Time's favorites file; every favorite in that file is
flagged on its sidecar for the phone.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import config
from util import favs_csv, lanes, sidecar, warm_gun, watch
from util.json_store import atomic_write_text, read_dict

log = logging.getLogger(__name__)

_FAVORITE_EVENTS = {"favorite": True, "unfavorite": False}
_COUNTED_EVENTS = {"completion": "completions", "skip": "skips", "lock": "locks"}
_CURSOR_FIELD = "applied_through"


@dataclass
class WatchWeightsResult:
    stamped: int = 0
    favorites_added: int = 0
    favorites_removed: int = 0
    unmapped: int = 0
    write_errors: int = 0

    @property
    def ok(self) -> bool:
        return not self.write_errors


def run() -> WatchWeightsResult:
    result = WatchWeightsResult()
    log.info("=== Stage: watch weights ===")
    events = warm_gun.read_journal(config.WARM_GUN_JOURNAL_DIR)
    videos = {event.path: warm_gun.library_video(event.path) for event in events}
    result.unmapped = sum(1 for event in events if videos[event.path] is None)
    _apply_phone_favorites(events, videos, result)
    phone_counts = _phone_counts(events, videos)
    fun_time_counts = read_dict(config.FUN_TIME_WATCH_STATS_FILE)
    favorites = {_key(video) for video in favs_csv.favorite_videos(config.FUN_TIME_FAVS_FILE)}
    for video in _played_videos():
        key = _key(video)
        counts = watch.add_counts(fun_time_counts.get(key), phone_counts.get(key))
        path = sidecar.sidecar_path(video)
        payload = sidecar.read(path)
        stamped = watch.stamped(payload, counts, favorite=key in favorites)
        if stamped != payload:
            sidecar.write(path, stamped)
            result.stamped += 1
    log.info(
        "Watch weights: stamped %d sidecar(s); phone favorites added %d, removed %d; "
        "%d journal line(s) named no video here.",
        result.stamped, result.favorites_added, result.favorites_removed, result.unmapped,
    )
    return result


def _played_videos() -> Iterator[Path]:
    for clip in lanes.ai_clips():
        yield clip.upscale
    yield from lanes.genau_clips()
    yield from lanes.non_ai_videos()


def _key(video: Path) -> str:
    return str(video).lower()


def _phone_counts(
    events: list[warm_gun.Event], videos: dict[str, Path | None]
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(watch.COUNT_FIELDS, 0))
    for event in events:
        video, field = videos[event.path], _COUNTED_EVENTS.get(event.event)
        if video is not None and field is not None:
            counts[_key(video)][field] += 1
    return counts


def _apply_phone_favorites(
    events: list[warm_gun.Event], videos: dict[str, Path | None], result: WatchWeightsResult
) -> None:
    if not config.FUN_TIME_FAVS_FILE.parent.is_dir():
        log.info("Fun Time is not installed here; the phone's favorites wait.")
        return
    cursor = read_dict(config.WARM_GUN_FAVORITES_CURSOR_FILE).get(_CURSOR_FIELD, -1)
    applied_through = cursor
    for event in events:
        if event.event not in _FAVORITE_EVENTS or event.t <= cursor:
            continue
        video = videos[event.path]
        if video is not None and video.exists():
            try:
                if _FAVORITE_EVENTS[event.event]:
                    result.favorites_added += favs_csv.add_favorite(config.FUN_TIME_FAVS_FILE, video)
                else:
                    result.favorites_removed += favs_csv.remove_favorite(config.FUN_TIME_FAVS_FILE, video)
            except OSError:
                log.exception("Could not write %s", config.FUN_TIME_FAVS_FILE)
                result.write_errors += 1
                break
        elif video is not None and warm_gun.played_video(event.path).exists():
            log.info("Phone %s of %s waits for its upscale.", event.event, video)
            break
        applied_through = event.t
    if applied_through != cursor:
        atomic_write_text(
            config.WARM_GUN_FAVORITES_CURSOR_FILE, json.dumps({_CURSOR_FIELD: applied_through})
        )
