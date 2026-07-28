"""The shape of the 2D/non_AI library both non-AI stages walk.

A bucket is whatever folder holds the numbered stage folders, because that is
the only thing every stage does with one: retire an original into its ``2*``,
publish an upscale into its ``3*``, scan its ``0*``/``1*`` for work.  Usually
that is a top-level folder like ``winston`` or ``other`` — except the ones
config excludes (``actually_AI_but_funscripted`` holds AI-pipeline outputs).

A top-level folder can also be split into sub-libraries that each keep their own
copy of the stages, and then the parent is not a bucket: it has no stages of its
own, and reading it as one leaves every stage hunting for folders that moved a
level down.  Each of those sub-libraries is a bucket instead.
"""

from __future__ import annotations

from pathlib import Path

import config

# A stage folder is named for its place in the pipeline: "0 unsorted", "1 could
# use work", "2 …", "3_good_to_go".  The leading digit is the whole convention.
_STAGE_DIGITS = "0123"


def is_stage_dir(path: Path) -> bool:
    """Whether *path* is one of a bucket's numbered stage folders."""
    return path.is_dir() and path.name[:1] in _STAGE_DIGITS


def holds_stages(folder: Path) -> bool:
    """Whether the stage folders sit directly in *folder*."""
    try:
        return any(is_stage_dir(child) for child in folder.iterdir())
    except OSError:
        return False


def _sub_libraries(folder: Path) -> list[Path]:
    """*folder*'s own copies of the pipeline, if it was split into some.

    Only its UNNUMBERED children can be one: the numbered children are its
    stages, and a stage holds numbered sub-stages of its own ("1 could use
    work/2_originals…"), so "holds stage folders" alone would read every stage
    as a library and every bucket as their parent.
    """
    try:
        children = sorted(folder.iterdir())
    except OSError:
        return []
    return [
        child
        for child in children
        if child.is_dir() and not is_stage_dir(child) and holds_stages(child)
    ]


def buckets() -> list[Path]:
    """Every bucket under the non-AI root, in path order.

    A top-level folder that holds the stages itself is one; a folder split into
    sub-libraries contributes each of those instead, and is not a bucket even
    while a leftover stage folder of its own is still standing — the split is
    what it is *for* now, and half-finished is still split.  The exclusion list
    names top-level folders, so it applies either way.
    """
    if not config.NON_AI_DIR.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(config.NON_AI_DIR.iterdir()):
        if not child.is_dir() or child.name in config.NONAI_EXCLUDED_BUCKETS:
            continue
        split = _sub_libraries(child)
        if split:
            found.extend(split)
        elif holds_stages(child):
            found.append(child)
    return found


def bucket_of(video: Path) -> Path | None:
    """The bucket *video* lives in, or None when it is in none of them.

    Read off the shape rather than the depth, so a split library resolves to the
    sub-library and an unsplit one to the top-level folder with no rule about
    which.  None for a video outside the library — and for one still sitting in
    a split folder's leftover stage, which belongs to no sub-library yet.
    """
    try:
        relative = video.relative_to(config.NON_AI_DIR)
    except ValueError:
        return None
    folder = config.NON_AI_DIR
    for part in relative.parts[:-1]:
        folder = folder / part
        if _sub_libraries(folder):
            continue
        if holds_stages(folder):
            return folder
    return None
