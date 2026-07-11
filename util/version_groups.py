"""Fold a bucket's non-AI videos into version families.

An enhanced variant is named by appending Topaz suffixes to its original's
stem (``foo`` -> ``foo_apo8_iris2``), so stripping those suffixes (see
:mod:`util.variants`) and then matching a shorter token-prefix reunites an
original with its variants — even when a hand-made variant keeps an extra
manual tag the plain strip leaves behind (``foo_3_apf2_iris2`` -> ``foo_3``,
still a token-prefix match for ``foo``).
"""
from __future__ import annotations

import re

from util.variants import strip_processing_suffixes

_SEPARATORS = re.compile(r"[-_ .]+")


def group_key_tokens(stem: str) -> tuple[str, ...]:
    """A stem reduced to its original's identifying tokens (lowercased)."""
    base = strip_processing_suffixes(stem).lower()
    return tuple(token for token in _SEPARATORS.split(base) if token)


def _is_prefix(shorter: tuple[str, ...], longer: tuple[str, ...]) -> bool:
    return len(shorter) <= len(longer) and longer[: len(shorter)] == shorter


def group_ids(stems: list[str]) -> dict[str, str]:
    """Map each stem to its family's group id — the original's stripped stem.

    Stems are matched shortest-family-first, so an original anchors the family
    its longer-named variants join; a variant joins the family whose tokens are
    a prefix of its own. The id is the anchor's suffix-stripped stem, so every
    variant of one scene shares a single stable, readable id.
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
                if atoks and _is_prefix(atoks, toks):
                    joined = anchor
                    break
        if joined is None:
            anchors.append(stem)
            anchor_tokens.append(toks)
            group_of[stem] = strip_processing_suffixes(stem)
        else:
            group_of[stem] = group_of[joined]
    return group_of
