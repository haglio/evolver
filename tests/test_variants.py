from __future__ import annotations

import ast
from pathlib import Path

import pytest
from app_support.video_names import UPSCALE_SUFFIX, strip_processing_suffixes

from tests.product_sources import PROJECT_ROOT, product_sources, strings_outside_docstrings
from util.variants import (
    is_processed_stem,
    is_upscaled_stem,
    sorted_stem_of,
    source_stem,
    upscaled_stem,
)


class TestIsProcessedStem:
    def test_true_when_a_suffix_is_present(self):
        assert is_processed_stem("clip_apo8_iris2")

    def test_false_for_plain_stem(self):
        assert not is_processed_stem("clip")


class TestTheUpscaleNamingRule:
    """"An upscale is named <sorted stem>_topaz" -- one declaration of it.

    Three stages, one utility, the backfill tool and two sibling repos read a
    file's provenance out of this rule, and it had no constant: six sites spelt
    it as a literal, each expressing it differently -- append, endswith, slice
    by len, regex-strip, containment in a suffix tuple.
    """

    def test_the_two_directions_are_inverses(self):
        assert upscaled_stem("clip one") == "clip one_topaz"
        assert sorted_stem_of("clip one_topaz") == "clip one"
        assert sorted_stem_of(upscaled_stem("clip one")) == "clip one"

    def test_a_stem_that_is_not_an_upscale_comes_back_whole(self):
        assert sorted_stem_of("clip one") == "clip one"
        assert not is_upscaled_stem("clip one")
        assert is_upscaled_stem("clip one_topaz")

    def test_it_takes_one_suffix_off_and_no_more(self):
        """The general strip is strip_processing_suffixes; this is the inverse
        of the upscale stage's own naming and nothing else."""
        assert sorted_stem_of("clip_apo8_topaz") == "clip_apo8"
        assert strip_processing_suffixes("clip_apo8_topaz") == "clip"


class TestSourceStem:
    @pytest.mark.parametrize(("stem", "expected"), [
        ("clip_topaz", "clip"),
        ("clip_topaz_cfr", "clip"),
        ("clip_apo8_gcg5_topaz", "clip_apo8_gcg5"),
        ("clip_apo8_gcg5", "clip"),
        ("clip_apo8_gcg5_Copy(2)", "clip"),
        ("clip_topaz_extra", "clip"),
        ("clip", "clip"),
        ("no_suffix_at_all", "no_suffix_at_all"),
        ("a_b_topaz", "a_b"),
        ("clip_apo8_gcg5_topaz_cfr", "clip_apo8_gcg5"),
    ])
    def test_strips_the_upscale_or_else_the_apo8_gcg5_chain_and_everything_after_it(self, stem, expected):
        assert source_stem(stem) == expected


class TestOnlyOneModuleSpellsIt:
    @pytest.mark.repo_check
    def test_the_suffix_is_a_literal_in_exactly_one_place(self):
        offenders = []
        for name in product_sources(PROJECT_ROOT):
            if name == "util/variants.py":
                continue
            tree = ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
            offenders += [
                f"{name}:{node.lineno}" for node in strings_outside_docstrings(tree)
                if UPSCALE_SUFFIX in node.value
            ]

        assert offenders == [], (
            "the upscale naming rule belongs to util.variants -- use "
            "upscaled_stem, sorted_stem_of or is_upscaled_stem"
        )
