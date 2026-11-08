from __future__ import annotations

from collections.abc import Mapping

from app_support.video_names import SEPARATORS, strip_processing_suffixes

from util.versions import is_version_marker


def group_key_tokens(stem: str) -> tuple[str, ...]:
    base = strip_processing_suffixes(stem).lower()
    return tuple(token for token in SEPARATORS.split(base) if token)


def _is_name_plus_version_markers(anchor: tuple[str, ...], stem: tuple[str, ...]) -> bool:
    if len(anchor) > len(stem) or stem[: len(anchor)] != anchor:
        return False
    return all(is_version_marker(token) for token in stem[len(anchor):])


def group_ids(stems: list[str], overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    group_of = _families_by_name(stems)
    for declared, anchor in (overrides or {}).items():
        anchors = _versions_of(anchor, stems)
        for stem in _versions_of(declared, stems) if anchors else ():
            group_of[stem] = group_of[anchors[0]]
    return group_of


def _families_by_name(stems: list[str]) -> dict[str, str]:
    order = {stem: i for i, stem in enumerate(stems)}
    tokens = {stem: group_key_tokens(stem) for stem in stems}
    anchors: list[str] = []
    anchor_tokens: list[tuple[str, ...]] = []
    group_of: dict[str, str] = {}
    for stem in sorted(stems, key=lambda s: (len(tokens[s]), order[s])):
        toks = tokens[stem]
        joined: str | None = None
        if toks:
            for anchor, atoks in zip(anchors, anchor_tokens, strict=True):
                if atoks and _is_name_plus_version_markers(atoks, toks):
                    joined = anchor
                    break
        if joined is None:
            anchors.append(stem)
            anchor_tokens.append(toks)
            group_of[stem] = strip_processing_suffixes(stem)
        else:
            group_of[stem] = group_of[joined]
    return group_of


def _versions_of(name: str, stems: list[str]) -> list[str]:
    original = strip_processing_suffixes(name)
    return [stem for stem in stems if strip_processing_suffixes(stem) == original]
