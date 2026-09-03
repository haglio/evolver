"""What a processed video variant's name says about its original.

The library names an upscaled/enhanced clip by appending the Topaz models that
made it: ``foo_apo8_iris2.mp4`` is ``foo.mp4`` after apo-8 interpolation and an
iris-2 upscale.  Stripping those suffixes recovers the original's stem, which
is how originals and their processed variants are matched across the tree.
"""

# What the AI upscale stage appends to a 1_sorted video's stem. It is the
# library's most-depended-on naming rule -- three stages, the backfill tool and
# two sibling repos read a file's provenance out of it -- and it was written
# out as a bare literal at six sites, each expressing it differently (append,
# endswith, slice by len, regex-strip, membership in a tuple).
UPSCALE_SUFFIX = "_topaz"


def upscaled_stem(sorted_stem: str) -> str:
    """The stem the upscale stage writes for the 1_sorted video *sorted_stem*."""
    return f"{sorted_stem}{UPSCALE_SUFFIX}"


def is_upscaled_stem(stem: str) -> bool:
    """Whether *stem* names an AI upscale rather than the video it came from."""
    return stem.endswith(UPSCALE_SUFFIX)


def sorted_stem_of(stem: str) -> str:
    """The 1_sorted stem an upscale came from — *stem* itself when it is not one.

    The exact inverse of :func:`upscaled_stem`, and only that: it takes one
    suffix off the end and nothing else. :func:`strip_processing_suffixes`
    below is the general form, which strips every Topaz token iteratively.
    """
    return stem[: -len(UPSCALE_SUFFIX)] if is_upscaled_stem(stem) else stem


# Elementary suffix tokens; composites like "_apo8_iris2" strip iteratively.
# "_topaz_cfr" stays composite because "_cfr" alone is too generic to strip.
PROCESSING_SUFFIXES = (
    f"{UPSCALE_SUFFIX}_cfr",
    UPSCALE_SUFFIX,
    "_gcg5",
    "_prob4",
    "_ghq5",
    "_iris3",
    "_iris2",
    "_apf2",
    "_apo8",
    "_enh",
)

# Words the user appends by hand to keep a second copy of a video distinct from
# the first — the pipeline never writes these, so they arrive as ordinary
# trailing tokens rather than as suffixes to strip. Kept short on purpose: each
# word here is one a real title can no longer be told apart by.
_MANUAL_VARIANT_TAGS = frozenset({"trimmed"})


def is_variant_marker(token: str) -> bool:
    """Whether *token* marks another copy of a video rather than naming one.

    A copy counter — bare or parenthesized, as Windows writes it saving a file
    that is already there — or one of the tags above.
    """
    return token.strip("()").isdigit() or token in _MANUAL_VARIANT_TAGS


def is_processed_stem(stem: str) -> bool:
    """Whether *stem* names a processed variant rather than an original."""
    return strip_processing_suffixes(stem) != stem


def strip_processing_suffixes(stem: str) -> str:
    """The stem with every trailing processing suffix removed."""
    while True:
        stripped = _strip_once(stem)
        if stripped == stem:
            return stem
        stem = stripped


def _strip_once(stem: str) -> str:
    for suffix in PROCESSING_SUFFIXES:
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem
