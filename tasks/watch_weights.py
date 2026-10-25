"""Stage: every app's viewing of a video summed on its sidecar as one weight,
and the phone's favorites marked there.

Fun Time's counts come from its own stats file, the phone's from Warm Gun's
journal, which reaches this machine inside the synced library.  The sum and
its weight go on the sidecar (``util.watch``), where Fun Time and Warm Gun
read one number instead of each keeping a formula.  A favorite made or taken
back on the phone goes onto the same sidecar, which is where Fun Time keeps
its own.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass
from pathlib import Path

from app_support.file_channel import write_whole

import config
from util import lanes, sidecar, warm_gun, watch
from util.json_reads import read_dict
from util.media_files import reachable

log = logging.getLogger(__name__)

_COUNTED_EVENTS = {"completion": "completions", "skip": "skips", "lock": "locks"}
_CURSOR_FIELD = "applied_through"


@dataclass
class WatchWeightsResult:
    stamped: int = 0
    favorites_added: int = 0
    favorites_removed: int = 0
    acts_named: int = 0
    unmapped: int = 0
    write_errors: int = 0

    @property
    def ok(self) -> bool:
        return not self.write_errors


@dataclass(frozen=True)
class _PhoneFavorites:
    """What marking the phone's favorites came to."""

    added: int = 0
    removed: int = 0
    write_errors: int = 0


def run() -> WatchWeightsResult:
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
    phone_favorites = _apply_phone_favorites(journals, videos)
    result.favorites_added = phone_favorites.added
    result.favorites_removed = phone_favorites.removed
    result.write_errors = phone_favorites.write_errors
    result.acts_named = _apply_picked_acts(journals, videos)
    phone_counts = _phone_counts(events, videos)
    fun_time_counts = read_dict(config.FUN_TIME_WATCH_STATS_FILE)
    for video in _played_videos():
        key = _key(video)
        counts = watch.add_counts(fun_time_counts.get(key), phone_counts.get(key))

        def stamp_the_watching(payload: dict, counts=counts) -> dict | None:
            stamped = watch.stamped(payload, counts)
            return stamped if stamped != payload else None

        if sidecar.update(sidecar.sidecar_path(video), stamp_the_watching) is not None:
            result.stamped += 1
    log.info(
        "Watch weights: stamped %d sidecar(s); phone favorites added %d, removed %d; "
        "%d picked act(s) written into records; %d journal line(s) named no video here.",
        result.stamped, result.favorites_added, result.favorites_removed, result.acts_named,
        result.unmapped,
    )
    return result


def _played_videos() -> Iterator[Path]:
    for clip in lanes.ai_clips():
        yield clip.upscale
    yield from lanes.genau_flicks()
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
    journals: dict[str, list[warm_gun.Event]], videos: dict[str, Path | None]
) -> _PhoneFavorites:
    """Each journal's favorites past that journal's own cursor."""
    carried = {True: 0, False: 0}

    def carry(event: warm_gun.Event) -> bool:
        video = videos[event.path]
        if video is not None and video.exists():
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


def _apply_picked_acts(
    journals: dict[str, list[warm_gun.Event]], videos: dict[str, Path | None]
) -> int:
    named = []

    def name_the_act(event: warm_gun.Event) -> bool:
        video = videos[event.path]
        if video is not None and video.exists():
            sidecar.record_action(video, event.action)
            named.append(video)
        return True

    _applied_once(journals, config.PICKED_ACTS_CURSOR_FILE, (warm_gun.ACT_EVENT,), name_the_act)
    return len(named)


def _applied_once(
    journals: dict[str, list[warm_gun.Event]], cursor_file: Path, kinds: Collection[str],
    apply: Callable[[warm_gun.Event], bool],
) -> None:
    """Hand *apply* each journal's events of *kinds* past that journal's own
    cursor, in time order, so each is applied once and another app may undo it.

    One time per file, not one across them: each machine uploads its whole
    file in its own time order, but the laptop's can reach the folder after
    the phone's later lines have been applied, and one time across both would
    skip its events for good.  *apply* answers False to hold the rest of its
    journal for a later run; an OSError from it holds every journal.
    """
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
    """How far each journal's events have been applied, by file name. The
    favorites' cursor used to hold one time for the one journal there was; that
    time was reached through the phone's file alone, so it holds that file back
    and no other."""
    stored = read_dict(cursor_file).get(_CURSOR_FIELD)
    if isinstance(stored, dict):
        return {name: int(t) for name, t in stored.items()}
    if isinstance(stored, int | float) and not isinstance(stored, bool):
        return {warm_gun.PHONE_JOURNAL: int(stored)}
    return {}
