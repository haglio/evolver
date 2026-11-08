from __future__ import annotations

import re

from app_support.video_names import UPSCALE_SUFFIX, strip_processing_suffixes


def upscaled_stem(sorted_stem: str) -> str:
    return f"{sorted_stem}{UPSCALE_SUFFIX}"


def is_upscaled_stem(stem: str) -> bool:
    return stem.endswith(UPSCALE_SUFFIX)


def sorted_stem_of(stem: str) -> str:
    return stem[: -len(UPSCALE_SUFFIX)] if is_upscaled_stem(stem) else stem


def source_stem(stem: str) -> str:
    stripped_topaz = re.sub(rf"{re.escape(UPSCALE_SUFFIX)}(?:_.*)?$", "", stem)
    if stripped_topaz != stem:
        return stripped_topaz
    return re.sub(r"_apo8_gcg5(?:_.*)?$", "", stem)


_HAND_ADDED_WORDS_TWO_TITLES_CAN_NO_LONGER_DIFFER_BY = frozenset({"trimmed"})


def is_version_marker(token: str) -> bool:
    return token.strip("()").isdigit() or token in _HAND_ADDED_WORDS_TWO_TITLES_CAN_NO_LONGER_DIFFER_BY


def is_processed_stem(stem: str) -> bool:
    return strip_processing_suffixes(stem) != stem

