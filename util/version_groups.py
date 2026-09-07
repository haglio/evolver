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

:func:`stable_title` is the same question asked strictly. The prefix rule above
is deliberately wide, so a copy the user tagged by hand joins its original; that
width is exactly wrong for a caller that has to know two files hold the same
footage before it decodes only one of them, so the strict reading requires the
whole reduced title to agree.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from util.variants import is_variant_marker, strip_processing_suffixes

_SEPARATORS = re.compile(r"[-_ .]+")

# Tokens dropped anywhere in a title because they name a quality, upscaler,
# codec, resolution or container rather than content. Deliberately a list
# rather than a rule: it can over-group (folding two different videos) or
# under-group (missing a tag nobody has listed), and is meant to be edited as
# new tags turn up in the library.
_QUALITY_TOKENS = frozenset({
    "topaz", "iris2", "old_iris2", "upscale", "upscaled", "remux",
    "x264", "x265", "hevc", "av1",
    "60fps", "30fps", "24fps",
    "480p", "540", "540p", "720p", "1080p", "1440p", "2160p", "4k",
    "mp4", "mkv", "web", "webrip",
})

# "old_iris2" carries an underscore, so it has to go before the separator split
# breaks it in two. Every multi-part quality token belongs here.
_MULTIPART_QUALITY = tuple(token for token in _QUALITY_TOKENS if "_" in token)

_HASH_TOKEN = re.compile(r"[a-z0-9]{6,12}")


def group_key_tokens(stem: str) -> tuple[str, ...]:
    """A stem reduced to its original's identifying tokens (lowercased)."""
    base = strip_processing_suffixes(stem).lower()
    return tuple(token for token in _SEPARATORS.split(base) if token)


def _is_hash_token(token: str) -> bool:
    """Whether *token* is one of the library's short alphanumeric file hashes.

    Both a letter and a digit are required, which is what keeps a plain word
    (``compilation``) and a plain number (a scene index) from reading as one.
    """
    if not _HASH_TOKEN.fullmatch(token):
        return False
    return any(c.isalpha() for c in token) and any(c.isdigit() for c in token)


def normalize_title(stem: str) -> str:
    """*stem* with its quality tags dropped and its trailing hash cut off."""
    text = stem.lower()
    for token in _MULTIPART_QUALITY:
        text = text.replace(token, " ")
    tokens = [t for t in _SEPARATORS.split(text) if t and t not in _QUALITY_TOKENS]
    while tokens and _is_hash_token(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def stable_title(stem: str) -> str:
    """*stem* reduced to what stays the same across versions of one cut.

    :func:`normalize_title` drops the tags a name may already carry; this also
    drops the ones the upscale stages append, so two stems are equal exactly
    when they are one video re-encoded. Empty for a name that is nothing but
    tags and a hash -- such a file is a version of nothing but itself.
    """
    return normalize_title(strip_processing_suffixes(stem))


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
    shares no prefix with its original (a 4K upscale of the best minutes of a
    scene, saved as "Jane Doe Scene Two 4k 60fps"), so it has to be declared.
    Each entry maps such a stem to the stem of the video it is a version of;
    with three versions, point them all at the same one rather than at each
    other.
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
