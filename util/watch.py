from __future__ import annotations

from app_support import watch_weights
from app_support.watch_weights import add_counts, weight_for

BLOCK = watch_weights.WATCH_BLOCK
WEIGHT_FIELD = watch_weights.WEIGHT_KEY


def stamped(payload: dict, counts: dict[str, int]) -> dict:
    result = {key: value for key, value in payload.items() if key != BLOCK}
    counts = add_counts(counts)
    if any(counts.values()):
        result[BLOCK] = {**counts, WEIGHT_FIELD: weight_for(counts)}
    return result
