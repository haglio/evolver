"""What a processed video variant's name says about its original.

The library names an upscaled/enhanced clip by appending the Topaz models that
made it: ``foo_apo8_iris2.mp4`` is ``foo.mp4`` after apo-8 interpolation and an
iris-2 upscale.  Stripping those suffixes recovers the original's stem, which
is how originals and their processed variants are matched across the tree.
"""

# Elementary suffix tokens; composites like "_apo8_iris2" strip iteratively.
# "_topaz_cfr" stays composite because "_cfr" alone is too generic to strip.
PROCESSING_SUFFIXES = (
    "_topaz_cfr",
    "_topaz",
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
