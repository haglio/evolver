"""Fold a bucket's non-AI videos into version families.

An enhanced variant is named by appending Topaz suffixes to its original's
stem (``foo`` -> ``foo_apo8_iris2``), so stripping those suffixes (see
:mod:`util.variants`) reunites the two. What can survive the strip is a marker
the user added by hand — a copy counter (``foo (2)``) or a tag like ``trimmed``
— so a variant reads as its original's tokens and then markers, nothing else.

Matching a bare token *prefix* is too loose to hold: every scene of a performer
starts with her name, so a stem that is only her name anchors all of them.

A version renamed rather than suffixed keeps no such thread back to its
original, so those pairs are declared instead (``config.NONAI_VERSION_OVERRIDES``).
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from util.variants import is_variant_marker, strip_processing_suffixes

_SEPARATORS = re.compile(r"[-_ .]+")


def group_key_tokens(stem: str) -> tuple[str, ...]:
    """A stem reduced to its original's identifying tokens (lowercased)."""
    base = strip_processing_suffixes(stem).lower()
    return tuple(token for token in _SEPARATORS.split(base) if token)


def _is_variant_of(anchor: tuple[str, ...], stem: tuple[str, ...]) -> bool:
    """Whether *stem* is *anchor*'s tokens and then nothing but variant markers."""
    if len(anchor) > len(stem) or stem[: len(anchor)] != anchor:
        return False
    return all(is_variant_marker(token) for token in stem[len(anchor):])


def group_ids(stems: list[str], overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Map each stem to its family's group id — the original's stripped stem.

    Stems are matched shortest-family-first, so an original anchors the family
    its longer-named variants join; a variant joins the family whose tokens
    begin its own and whose remainder is nothing but variant markers. The id is
    the anchor's suffix-stripped stem, so every variant of one scene shares a
    single stable, readable id.

    *overrides* names the pairs the rule cannot see: a version renamed by hand
    shares no prefix with its original (a 4K upscale of the best eight minutes,
    saved as "Performer POV BJ 4k 60fps"), so it has to be declared. Each entry
    maps such a stem to the stem of the video it is a version of; with three
    versions, point them all at the same one rather than at each other.
    """
    order = {stem: i for i, stem in enumerate(stems)}
    tokens = {stem: group_key_tokens(stem) for stem in stems}
    anchors: list[str] = []
    anchor_tokens: list[tuple[str, ...]] = []
    group_of: dict[str, str] = {}
    for stem in sorted(stems, key=lambda s: (len(tokens[s]), order[s])):
        toks = tokens[stem]
        joined: str | None = None
        if toks:
            for anchor, atoks in zip(anchors, anchor_tokens):
                if atoks and _is_variant_of(atoks, toks):
                    joined = anchor
                    break
        if joined is None:
            anchors.append(stem)
            anchor_tokens.append(toks)
            group_of[stem] = strip_processing_suffixes(stem)
        else:
            group_of[stem] = group_of[joined]
    for stem, anchor in (overrides or {}).items():
        # Only within one bucket: group_ids sees a bucket at a time, and a
        # declared pair split across two of them is not a family Evolver can
        # record anyway.
        if stem in group_of and anchor in group_of:
            group_of[stem] = group_of[anchor]
    return group_of
