"""The watch block on a sidecar: every app's viewing of one video, summed, and
the playback weight that sum earns.  Written by ``tasks.watch_weights`` and
read by Fun Time and Warm Gun, so the formula lives here alone."""

from __future__ import annotations

BLOCK = "watch"
FAVORITE_FIELD = "favorite"
COUNT_FIELDS = ("completions", "skips", "locks")
STAMPED_KEYS = frozenset({BLOCK, FAVORITE_FIELD})

# score = completions + 3*locks - skips, softened by /3 and clamped so one
# video can be at most 8x more (or 8x less) frequent than a fresh one.
_LOCK_SCORE = 3.0
_SCORE_SOFTENING = 3.0
_MAX_DOUBLINGS = 3.0


def weight_for(counts: dict | None) -> float:
    if not counts:
        return 1.0
    score = (
        counts.get("completions", 0)
        + _LOCK_SCORE * counts.get("locks", 0)
        - counts.get("skips", 0)
    )
    doublings = max(-_MAX_DOUBLINGS, min(_MAX_DOUBLINGS, score / _SCORE_SOFTENING))
    return float(2.0 ** doublings)


def add_counts(*sources: dict | None) -> dict[str, int]:
    total = dict.fromkeys(COUNT_FIELDS, 0)
    for source in sources:
        for field in COUNT_FIELDS:
            total[field] += int((source or {}).get(field) or 0)
    return total


def stamped(payload: dict, counts: dict[str, int], *, favorite: bool) -> dict:
    result = {key: value for key, value in payload.items() if key not in STAMPED_KEYS}
    counts = add_counts(counts)
    if any(counts.values()):
        result[BLOCK] = {**counts, "weight": weight_for(counts)}
    if favorite:
        result[FAVORITE_FIELD] = True
    return result
