from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from util import orientation, topaz

NOTHING_TO_DO = "nothing to do"
DONE, WRONG, FOUND = "done", "wrong", "found"


FlickWords = tuple[str, str]


def _which(count: int, many: str, one: str, flick_words: FlickWords) -> str:
    flick, flicks = flick_words
    return (one if count == 1 and one else many).format(flick=flick, flicks=flicks)


@dataclass(frozen=True)
class Count:
    key: str
    many: str
    one: str = ""
    even_at_zero: bool = False
    kind: str = FOUND

    def said(self, result: dict[str, Any], flick_words: FlickWords) -> str | None:
        value = result.get(self.key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        if not value and not self.even_at_zero:
            return None
        return f"{value} {_which(value, self.many, self.one, flick_words)}"

    def happened(self, result: dict[str, Any]) -> bool:
        value = result.get(self.key)
        return isinstance(value, (int, float)) and not isinstance(value, bool) and bool(value)


@dataclass(frozen=True)
class Named:
    key: str
    many: str
    one: str = ""
    kind: str = WRONG

    def said(self, result: dict[str, Any], flick_words: FlickWords) -> str | None:
        names = list(result.get(self.key) or [])
        if not names:
            return None
        return f"{len(names)} {_which(len(names), self.many, self.one, flick_words)} ({_name_sample(names)})"

    def happened(self, result: dict[str, Any]) -> bool:
        return bool(result.get(self.key))


@dataclass(frozen=True)
class Groups:
    key: str
    many: str
    one: str = ""
    kind: str = WRONG

    def said(self, result: dict[str, Any], flick_words: FlickWords) -> str | None:
        count = len(result.get(self.key) or ())
        return f"{count} {_which(count, self.many, self.one, flick_words)}" if count else None

    def happened(self, result: dict[str, Any]) -> bool:
        return bool(result.get(self.key))


@dataclass(frozen=True)
class Flag:
    key: str
    words: str
    kind: str = WRONG

    def said(self, result: dict[str, Any], flick_words: FlickWords) -> str | None:
        return self.words if result.get(self.key) is True else None

    def happened(self, result: dict[str, Any]) -> bool:
        return result.get(self.key) is True


@dataclass(frozen=True)
class Text:
    key: str
    words: str = "{}"
    kind: str = DONE

    def said(self, result: dict[str, Any], flick_words: FlickWords) -> str | None:
        value = result.get(self.key)
        return self.words.format(value) if isinstance(value, str) and value else None

    def happened(self, result: dict[str, Any]) -> bool:
        value = result.get(self.key)
        return isinstance(value, str) and bool(value)


@dataclass(frozen=True)
class Sentence:
    parts: tuple[Count | Named | Groups | Flag | Text, ...]

    def said(self, result: dict[str, Any], flick_words: FlickWords) -> str:
        if any(part.kind != FOUND and part.happened(result) for part in self.parts):
            return ", ".join(words for part in self.parts if (words := part.said(result, flick_words)))
        return nothing_to_do([part.said(result, flick_words) for part in self.parts if part.happened(result)])


def nothing_to_do(found: list[str]) -> str:
    return f"{NOTHING_TO_DO} ({', '.join(found)})" if found else NOTHING_TO_DO


_NEITHER = f"{orientation.PORTRAIT} nor {orientation.LANDSCAPE}"

SENTENCES: dict[str, Sentence] = {
    "strays": Sentence((
        Count("renamed", "video names fixed", "video name fixed", kind=DONE),
        Count("rehomed_scripts", "funscripts moved to the scripts folder",
              "funscript moved to the scripts folder", kind=DONE),
        Named("reported", "other files reported", "other file reported"),
    )),
    "withdrawn": Sentence((
        Count("deleted", "videos deleted", "video deleted", kind=DONE),
        Count("deleted_flicks", "{flicks} deleted", "{flick} deleted", kind=DONE),
        Count("deleted_scripts", "funscripts deleted", "funscript deleted", kind=DONE),
        Count("failed", "could not be deleted", kind=WRONG),
    )),
    "metadata": Sentence((
        Count("newly_scraped", "prompts read", "prompt read", even_at_zero=True, kind=DONE),
        Count("handed_over", "handed to Origenerator's gallery", kind=DONE),
        Count("errors", "failed to read", even_at_zero=True, kind=WRONG),
        Count("already_scraped", "already read"),
        Count("skipped_failed", "failed before and not tried again"),
        Count("no_scrape_strat", "from a site Evolver hasn't been taught how to read prompts from yet"),
    )),
    "sort": Sentence((
        Count("moved", "moved into `1_sorted`", kind=DONE),
        Count("made_again", "made again and put in place of the old copy", kind=DONE),
        Count("deleted_collisions", "already in `1_sorted` and deleted from `0_inbox`", kind=DONE),
        Count("skipped_unknown", f"left in `0_inbox` because they are neither {_NEITHER}",
              f"left in `0_inbox` because it is neither {_NEITHER}", kind=WRONG),
    )),
    "origenerator_downtime": Sentence((
        Text("did"),
        Flag("holds_the_graphics_card", "a LoRA is training on the graphics card", kind=FOUND),
        Flag("failed", "Evolver could not ask Origenerator what to do while it is closed"),
    )),
    "upscale": Sentence((
        Count("processed", "enhanced", kind=DONE),
        Count("failed", "failed", kind=WRONG),
        Count("stopped_at_budget", "left for the next run because this run's time for "
                                   "enhancing was up"),
        Count("pending_after_run", "still waiting to be enhanced"),
        Flag("deferred_low_disk", "held back because the disk is nearly full"),
    )),
    "genau_deliver": Sentence((
        Count("delivered", "delivered to Genau's folder", kind=DONE),
        Count("failed", "failed", kind=WRONG),
    )),
    "funscript_drafts": Sentence((
        Count("made", "funscripts made", "funscript made", kind=DONE),
        Count("started", "videos sent to GoblinScript", "video sent to GoblinScript", kind=DONE),
        Count("waiting", "videos still waiting for a funscript", "video still waiting for a funscript"),
        Count("nothing_usable", "videos GoblinScript made nothing usable for",
              "video GoblinScript made nothing usable for"),
        Count("failed_batches", "times GoblinScript wrote nothing", "time GoblinScript wrote nothing", kind=WRONG),
        Count("already_scripted", "videos already have a funscript", "video already has a funscript"),
    )),
    "verify": Sentence((
        Count("sorted_count", "`1_sorted` videos", "`1_sorted` video", even_at_zero=True),
        Count("sorted_flicks", "`1_sorted` {flicks}", "`1_sorted` {flick}"),
        Count("upscale_count", "enhanced videos", "enhanced video", even_at_zero=True),
        Count("upscale_flicks", "enhanced {flicks}", "enhanced {flick}"),
        Named("orphan_upscales", "enhanced videos without their `1_sorted` video",
              "enhanced video without its `1_sorted` video"),
        Named("orphan_sorted", "`1_sorted` videos without their enhanced video",
              "`1_sorted` video without its enhanced video"),
        Named("orphan_sorted_flicks", "`1_sorted` {flicks} without their enhanced {flick}",
              "`1_sorted` {flick} without its enhanced {flick}"),
        Named("duplicates", "enhanced video names in more than one place",
              "enhanced video name in more than one place"),
        Named("duplicate_flicks", "enhanced {flick} names in more than one place",
              "enhanced {flick} name in more than one place"),
        Named("missing_flicks", "sent to Genau but missing from Genau's folder"),
    )),
    "watch_weights": Sentence((
        Count("stamped", "weights updated", "weight updated", kind=DONE),
        Count("already", "weights already up to date", "weight already up to date"),
        Count("favorites_added", "phone favorites added", "phone favorite added", kind=DONE),
        Count("favorites_removed", "phone favorites removed", "phone favorite removed", kind=DONE),
        Count("unmapped", "Fun Time or Warm Gun records name no video here",
              "Fun Time or Warm Gun record names no video here"),
        Count("write_errors", "could not be saved", kind=WRONG),
        Flag("gallery_untold", "Origenerator's gallery could not be told"),
    )),
    "bookmarks": Sentence((
        Count("added", "bookmarks added", "bookmark added", kind=DONE),
        Count("removed", "bookmarks removed", "bookmark removed", kind=DONE),
        Count("already", "already bookmarked"),
        Count("untaught", "for a site Evolver hasn't been taught to link to yet"),
        Count("no_url", "favorites have no web page", "favorite has no web page"),
        Count("bad_url", "favorites have a page that is not a web address",
              "favorite has a page that is not a web address", kind=WRONG),
        Flag("profile_missing", "Chrome profile not found"),
        Text("write_error", "could not write the bookmarks: {}", kind=WRONG),
        Flag("gallery_unread", "could not read Origenerator's gallery"),
    )),
    "clip_scripts": Sentence((
        Count("written", "clips given a funscript", "clip given a funscript", kind=DONE),
        Count("already_scripted", "clips already had one", "clip already had one"),
        Count("no_scene_script", "scenes have no funscript", "scene has no funscript"),
        Count("no_motion_in_window", "clips have no motion in their part of the scene",
              "clip has no motion in its part of the scene"),
        Count("unprobeable", "clips could not be measured", "clip could not be measured", kind=WRONG),
        Count("unmatched_clip", "clips' scenes not found", "clip's scene not found"),
    )),
    "scene_scripts": Sentence((
        Count("written", "scenes given a funscript", "scene given a funscript", kind=DONE),
        Count("already_scripted", "scenes already had one", "scene already had one"),
        Count("no_clip_script", "clips have no funscript", "clip has no funscript"),
        Count("scene_gone", "scenes no longer in the library", "scene no longer in the library"),
        Count("unprobeable", "scenes could not be measured", "scene could not be measured", kind=WRONG),
        Count("unmatched_clip", "clips' scenes not found", "clip's scene not found"),
    )),
    "group_non_ai": Sentence((
        Count("grouped", "videos", "video"),
        Count("families", "groups", "group"),
        Count("joined", "of the groups found by comparing frames"),
        Count("measured", "videos compared this run", "video compared this run", kind=DONE),
        Count("written", "sidecars written", "sidecar written", kind=DONE),
        Count("pruned", "sidecars removed because their video is gone",
              "sidecar removed because its video is gone", kind=DONE),
    )),
    "title_non_ai": Sentence((
        Count("titled", "videos named", "video named"),
        Count("videos", "videos looked at", "video looked at"),
        Count("written", "sidecars written", "sidecar written", kind=DONE),
    )),
    "video_types": Sentence((
        Count("recorded", "recorded", kind=DONE),
        Count("already", "already recorded"),
        Count("skipped", "could not be measured", kind=WRONG),
        Count("deferred", "left for the next run"),
    )),
    "provenance": Sentence((
        Count("from_notes", "read from Topaz's note", kind=DONE),
        Count("unknown", "marked unknown", kind=DONE),
        Count("already", "already recorded"),
        Count("deferred", "left for the next run"),
    )),
    "labels": Sentence((
        Count("copied", "videos given their actions", "video given its actions", kind=DONE),
        Count("already", "already had them"),
    )),
    "dupes": Sentence((
        Count("scanned_count", "videos checked", "video checked", even_at_zero=True),
        Groups("duplicate_groups", "groups of videos with the same size",
               "group of videos with the same size"),
    )),
    "pcloud_stuck": Sentence((
        Count("deleted_in_cloud", "deletions finished in the cloud", "deletion finished in the cloud", kind=DONE),
        Count("dropped", "changes with nothing left to do taken off pCloud's list",
              "change with nothing left to do taken off pCloud's list", kind=DONE),
        Count("retried", "uploads tried again", "upload tried again", kind=DONE),
        Count("left", "changes left for a look", "change left for a look"),
    )),
}

SKIP_REASONS: dict[str, str] = {
    "no_pending_work": NOTHING_TO_DO,
    "origenerator_training":
        "waited while a LoRA started with Origenerator's Train button trained on the graphics card",
    "topaz_busy": "waited while Topaz enhanced a video Evolver did not start",
    "cpu_busy": "waited because the computer's processor was too busy",
    "session_live": "waited while a Funestra was playing",
    "goblinscript_not_installed": "waited because GoblinScript is not installed where Evolver's settings say",
    "goblinscript_still_drafting": "waited while GoblinScript made funscripts for the videos it was sent",
    "goblinscript_failed":
        "waited because GoblinScript wrote nothing for the last videos it was sent; they are sent "
        "again an hour after that",
    topaz.SIGN_IN_EXPIRED:
        "waited because Topaz Video's sign-in has expired; open the Topaz Video app and sign in",
    "upscale_pending":
        "waited because AI videos are still waiting to be enhanced, so the check would report "
        "false mismatches",
}


def details_of(
    result: dict[str, Any] | None,
    skip_reason: str | None,
    stage_key: str,
    flick_words: FlickWords,
) -> str:
    if skip_reason:
        return SKIP_REASONS.get(skip_reason, skip_reason)
    if not result:
        return ""
    summarize: Callable[[dict[str, Any]], str] | None = _SUMMARIZERS.get(stage_key)
    if summarize is not None:
        return summarize(result)
    sentence = SENTENCES.get(stage_key)
    return sentence.said(result, flick_words) if sentence is not None else ""


_SCRIPTS_PROBLEMS = (
    ("unmatched", "match no video", "unmatched_paths"),
    ("ambiguous", "match more than one video", "ambiguous_paths"),
    ("collisions", "cannot move — a different script holds the destination", "collision_paths"),
    ("ambiguous_variant_groups", "version groups whose scripts differ — none copied", None),
    ("variant_copy_errors", "failed to copy to a version", "variant_copy_error_paths"),
)
_SCRIPTS_ROUTINE = (
    ("moved", "moved into place"),
    ("copied_variants", "copied to a version"),
    ("rehomed_to_variants", "rehomed to a version still in the library"),
    ("followed_to_archive", "followed a retired video out of the library"),
    ("followed_renames", "followed a video renamed by hand"),
    ("discarded_duplicates", "duplicate discarded"),
)
_SCRIPTS_ALREADY_ALIGNED = ("already_aligned", "already aligned")
_SCRIPTS_NAMES_SHOWN = 3


def _summarize_scripts_sync(result: dict[str, Any]) -> str:
    problems = [_naming(f"{result[key]} {label}", result.get(names) or [])
                for key, label, names in _SCRIPTS_PROBLEMS
                if isinstance(result.get(key), int) and result[key]]
    unreachable = " and ".join(result.get("unreachable") or [])
    not_checked = ([f"{result['not_checked']} not checked: {unreachable} cannot be reached"]
                   if result.get("not_checked") else [])
    routine = [] if problems else _counted(result, (*_SCRIPTS_ROUTINE, _SCRIPTS_ALREADY_ALIGNED))
    if not (problems or not_checked or _counted(result, _SCRIPTS_ROUTINE)):
        return nothing_to_do(routine or ["no funscripts"])
    said = problems + not_checked + ([", ".join(routine)] if routine else [])
    return "; ".join(said)


def _counted(result: dict[str, Any], labeled: tuple[tuple[str, str], ...]) -> list[str]:
    return [f"{result[key]} {label}" for key, label in labeled
            if isinstance(result.get(key), int) and result[key]]


def _naming(said: str, names: list[str]) -> str:
    return f"{said} ({_name_sample(names)})" if names else said


def _name_sample(names: list[str]) -> str:
    shown = ", ".join(names[:_SCRIPTS_NAMES_SHOWN])
    remainder = len(names) - _SCRIPTS_NAMES_SHOWN
    return f"{shown} +{remainder} more" if remainder > 0 else shown


def _summarize_nonai_upscale(result: dict[str, Any]) -> str:
    parts = []
    asked_for = " at your request" if result.get("on_request") else ""
    if result.get("started"):
        parts.append(f"started {result['started']}{asked_for}")
    if result.get("unreachable_archive"):
        parts.append(f"finished {result['in_flight']}, waiting until "
                     f"{result['unreachable_archive']} can be reached to take the original")
    elif result.get("in_flight"):
        parts.append(f"encoding {result['in_flight']} ({_encode_state(result)})")
    if result.get("promoted"):
        parts.append(f"finished {result['promoted']}")
    if result.get("stopped"):
        parts.append(f"stopped {result['stopped']} (still queued)")
    if result.get("failed"):
        parts.append(f"failed {result['failed']}")
    if result.get("deferred_low_disk"):
        held_back = "held back because the disk is nearly full"
        if not parts:
            return f"{held_back} ({_whats_left(result)})"
        parts.append(held_back)
    elif result.get("start_deferred") and not result.get("in_flight"):
        waiting = f"waiting ({result['start_deferred']})"
        if not parts:
            return nothing_to_do([waiting, _whats_left(result)])
        parts.append(waiting)
    if not parts:
        return nothing_to_do([_whats_left(result)])
    parts.append(_whats_left(result))
    return ", ".join(parts)


def _whats_left(result: dict[str, Any]) -> str:
    left = f"{result.get('pending', 0)} queued"
    percent = result.get("percent_complete")
    if percent is None:
        return left
    hours = (result.get("remaining_seconds") or 0.0) / 3600
    unmeasured = result.get("unmeasured_videos") or 0
    missing = f", {unmeasured} not yet measured" if unmeasured else ""
    return f"{left}, {hours:.1f}h left, {percent}% done{missing}"


def _encode_state(result: dict[str, Any]) -> str:
    percent = result.get("in_flight_percent")
    state = "progress unknown" if percent is None else f"{percent}%"
    if result.get("suspended"):
        state += ", paused: you're at the computer"
    if result.get("on_request"):
        state += ", at your request"
    return state


_SUMMARIZERS = {
    "upscale_non_ai": _summarize_nonai_upscale,
    "scripts": _summarize_scripts_sync,
}
