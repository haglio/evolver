from __future__ import annotations

from typing import Any

_HEADLINE_FIELDS = {
    "metadata": ("newly_scraped", "errors"),
}


def details_of(
    result: dict[str, Any] | None,
    skip_reason: str | None = None,
    stage_key: str = "",
) -> str:
    if skip_reason:
        return f"Reason: {skip_reason}"
    if not result:
        return ""
    custom = _SUMMARIZERS.get(stage_key)
    if custom is not None:
        return custom(result)
    headline = _HEADLINE_FIELDS.get(stage_key, ())
    parts = [f"{key}={result[key]}" for key in headline
             if isinstance(result.get(key), (int, float))]
    for key, value in result.items():
        if key in headline:
            continue
        if isinstance(value, (int, float)) and value and not key.startswith("_"):
            parts.append(f"{key}={value}")
    return ", ".join(parts[:5])


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
