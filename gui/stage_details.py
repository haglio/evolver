from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from util import orientation, topaz

NOTHING_TO_DO = "Nothing to do"


def _which(count: int, many: str, one: str) -> str:
    return one if count == 1 and one else many


@dataclass(frozen=True)
class Count:
    key: str
    many: str
    one: str = ""
    even_at_zero: bool = False

    def said(self, result: dict[str, Any]) -> str | None:
        value = result.get(self.key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        if not value and not self.even_at_zero:
            return None
        return f"{value} {_which(value, self.many, self.one)}"


@dataclass(frozen=True)
class Named:
    key: str
    many: str
    one: str = ""

    def said(self, result: dict[str, Any]) -> str | None:
        names = list(result.get(self.key) or [])
        if not names:
            return None
        return f"{len(names)} {_which(len(names), self.many, self.one)} ({_name_sample(names)})"


@dataclass(frozen=True)
class Groups:
    key: str
    many: str
    one: str = ""

    def said(self, result: dict[str, Any]) -> str | None:
        count = len(result.get(self.key) or ())
        return f"{count} {_which(count, self.many, self.one)}" if count else None


@dataclass(frozen=True)
class Flag:
    key: str
    words: str

    def said(self, result: dict[str, Any]) -> str | None:
        return self.words if result.get(self.key) is True else None


@dataclass(frozen=True)
class Text:
    key: str
    words: str = "{}"

    def said(self, result: dict[str, Any]) -> str | None:
        value = result.get(self.key)
        return self.words.format(value) if isinstance(value, str) and value else None


@dataclass(frozen=True)
class Sentence:
    parts: tuple[Count | Named | Groups | Flag | Text, ...]

    def said(self, result: dict[str, Any]) -> str:
        said = [words for part in self.parts if (words := part.said(result))]
        return ", ".join(said) if said else NOTHING_TO_DO


_NEITHER = f"{orientation.PORTRAIT} nor {orientation.LANDSCAPE}"

SENTENCES: dict[str, Sentence] = {
    "strays": Sentence((
        Count("renamed", "video names fixed", "video name fixed"),
        Count("rehomed_scripts", "funscripts moved to the scripts folder",
              "funscript moved to the scripts folder"),
        Named("reported", "other files reported", "other file reported"),
    )),
    "withdrawn": Sentence((
        Count("deleted", "videos deleted", "video deleted"),
        Count("deleted_scripts", "funscripts deleted", "funscript deleted"),
        Count("failed", "could not be deleted"),
    )),
    "metadata": Sentence((
        Count("newly_scraped", "prompts read", "prompt read", even_at_zero=True),
        Count("handed_over", "handed to Origenerator's gallery"),
        Count("errors", "failed to read", even_at_zero=True),
        Count("already_scraped", "already read"),
        Count("skipped_failed", "failed before and not tried again"),
        Count("no_scrape_strat", "from a site Evolver cannot read prompts from"),
    )),
    "sort": Sentence((
        Count("moved", "moved into 1_sorted"),
        Count("made_again", "made again and put in place of the old copy"),
        Count("deleted_collisions", "already in 1_sorted and deleted from 0_inbox"),
        Count("skipped_unknown", f"left in 0_inbox because they are neither {_NEITHER}",
              f"left in 0_inbox because it is neither {_NEITHER}"),
    )),
    "origenerator_downtime": Sentence((
        Text("did"),
        Flag("holds_the_graphics_card", "a LoRA is training on the graphics card"),
        Flag("failed", "Evolver could not ask Origenerator what to do while it is closed"),
    )),
    "upscale": Sentence((
        Count("processed", "enhanced"),
        Count("failed", "failed"),
        Count("stopped_at_budget", "left for the next run because this run's time for "
                                   "enhancing was up"),
        Count("pending_after_run", "still waiting to be enhanced"),
        Flag("deferred_low_disk", "held back: low disk"),
    )),
    "genau_deliver": Sentence((
        Count("delivered", "delivered to Genau's folder"),
        Count("failed", "failed"),
    )),
    "verify": Sentence((
        Count("sorted_count", "1_sorted videos", "1_sorted video", even_at_zero=True),
        Count("upscale_count", "enhanced videos", "enhanced video", even_at_zero=True),
        Named("orphan_upscales", "enhanced videos without their 1_sorted video",
              "enhanced video without its 1_sorted video"),
        Named("orphan_sorted", "1_sorted videos without their enhanced video",
              "1_sorted video without its enhanced video"),
        Named("duplicates", "enhanced video names in more than one place",
              "enhanced video name in more than one place"),
        Named("missing_flicks", "sent to Genau but missing from Genau's folder"),
    )),
    "watch_weights": Sentence((
        Count("stamped", "weights saved", "weight saved"),
        Count("favorites_added", "phone favorites added", "phone favorite added"),
        Count("favorites_removed", "phone favorites removed", "phone favorite removed"),
        Count("unmapped", "Fun Time or Warm Gun records name no video here",
              "Fun Time or Warm Gun record names no video here"),
        Count("write_errors", "could not be saved"),
        Flag("gallery_untold", "Origenerator's gallery could not be told"),
    )),
    "bookmarks": Sentence((
        Count("synced", "bookmarks written", "bookmark written"),
        Count("no_url", "favorites have no web page", "favorite has no web page"),
        Count("bad_url", "favorites have a page that is not a web address",
              "favorite has a page that is not a web address"),
        Flag("profile_missing", "Chrome profile not found"),
        Text("write_error", "could not write the bookmarks: {}"),
        Flag("gallery_unread", "could not read Origenerator's gallery"),
    )),
    "clip_scripts": Sentence((
        Count("written", "clips given a funscript", "clip given a funscript"),
        Count("already_scripted", "clips already had one", "clip already had one"),
        Count("no_scene_script", "scenes have no funscript", "scene has no funscript"),
        Count("no_motion_in_window", "clips have no motion in their part of the scene",
              "clip has no motion in its part of the scene"),
        Count("unprobeable", "clips could not be measured", "clip could not be measured"),
        Count("unmatched_clip", "clips' scenes not found", "clip's scene not found"),
    )),
    "scene_scripts": Sentence((
        Count("written", "scenes given a funscript", "scene given a funscript"),
        Count("already_scripted", "scenes already had one", "scene already had one"),
        Count("no_clip_script", "clips have no funscript", "clip has no funscript"),
        Count("scene_gone", "scenes no longer in the library", "scene no longer in the library"),
        Count("unprobeable", "scenes could not be measured", "scene could not be measured"),
        Count("unmatched_clip", "clips' scenes not found", "clip's scene not found"),
    )),
    "group_non_ai": Sentence((
        Count("grouped", "videos", "video"),
        Count("families", "groups", "group"),
        Count("joined", "of the groups found by comparing frames"),
        Count("measured", "videos compared this run", "video compared this run"),
        Count("written", "sidecars written", "sidecar written"),
        Count("pruned", "sidecars removed because their video is gone",
              "sidecar removed because its video is gone"),
    )),
    "title_non_ai": Sentence((
        Count("titled", "videos named", "video named"),
        Count("videos", "videos looked at", "video looked at"),
        Count("written", "sidecars written", "sidecar written"),
    )),
    "video_types": Sentence((
        Count("recorded", "recorded"),
        Count("already", "already recorded"),
        Count("skipped", "could not be measured"),
        Count("deferred", "left for the next run"),
    )),
    "provenance": Sentence((
        Count("from_notes", "read from Topaz's note"),
        Count("unknown", "marked unknown"),
        Count("already", "already recorded"),
        Count("deferred", "left for the next run"),
    )),
    "labels": Sentence((
        Count("copied", "videos given their actions", "video given its actions"),
        Count("already", "already had them"),
    )),
    "dupes": Sentence((
        Count("scanned_count", "videos checked", "video checked", even_at_zero=True),
        Groups("duplicate_groups", "groups of videos with the same size",
               "group of videos with the same size"),
    )),
}

SKIP_REASONS: dict[str, str] = {
    "no_pending_work": "Nothing is waiting to be enhanced",
    "origenerator_training":
        "Waited: a LoRA started with Origenerator's Train button is training on the graphics card",
    "topaz_busy": "Waited: Topaz is enhancing a video Evolver did not start",
    "cpu_busy": "Waited: the computer's processor was too busy",
    topaz.SIGN_IN_EXPIRED:
        "Waited: Topaz Video's sign-in has expired; open the Topaz Video app and sign in",
    "upscale_pending":
        "Waited: AI videos are still waiting to be enhanced, so the check would report "
        "false mismatches",
}


def details_of(
    result: dict[str, Any] | None,
    skip_reason: str | None = None,
    stage_key: str = "",
) -> str:
    if skip_reason:
        return SKIP_REASONS.get(skip_reason, skip_reason)
    if not result:
        return ""
    summarize: Callable[[dict[str, Any]], str] | None = _SUMMARIZERS.get(stage_key)
    if summarize is not None:
        return summarize(result)
    sentence = SENTENCES.get(stage_key)
    return sentence.said(result) if sentence is not None else ""


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
    ("already_aligned", "already aligned"),
)
_SCRIPTS_NAMES_SHOWN = 3


def _summarize_scripts_sync(result: dict[str, Any]) -> str:
    problems = [_naming(f"{result[key]} {label}", result.get(names) or [])
                for key, label, names in _SCRIPTS_PROBLEMS
                if isinstance(result.get(key), int) and result[key]]
    unreachable = " and ".join(result.get("unreachable") or [])
    not_checked = ([f"{result['not_checked']} not checked: {unreachable} cannot be reached"]
                   if result.get("not_checked") else [])
    routine = [] if problems else [f"{result[key]} {label}" for key, label in _SCRIPTS_ROUTINE
                                   if isinstance(result.get(key), int) and result[key]]
    said = problems + not_checked + ([", ".join(routine)] if routine else [])
    return "; ".join(said) if said else "no funscripts"


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
        parts.append("held back: low disk")
    elif result.get("start_deferred") and not result.get("in_flight"):
        parts.append(f"waiting ({result['start_deferred']})")
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
    return f"{left} ({hours:.1f}h left, {percent}% done{missing})"


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
