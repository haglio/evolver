import ast
from pathlib import Path

from tests.product_sources import PROJECT_ROOT, product_sources
from util.variants import (
    UPSCALE_SUFFIX,
    is_processed_stem,
    is_upscaled_stem,
    sorted_stem_of,
    strip_processing_suffixes,
    upscaled_stem,
)


class TestStripProcessingSuffixes:
    def test_strips_single_model_suffix(self):
        assert strip_processing_suffixes("clip_iris2") == "clip"

    def test_strips_composite_model_chains(self):
        assert strip_processing_suffixes("clip_apo8_iris2") == "clip"
        assert strip_processing_suffixes("clip_apo8_prob4") == "clip"
        assert strip_processing_suffixes("clip_apo8_ghq5") == "clip"
        assert strip_processing_suffixes("clip_apo8_gcg5_topaz") == "clip"
        assert strip_processing_suffixes("clip_apo8_gcg5_topaz_cfr") == "clip"

    def test_plain_stem_unchanged(self):
        assert strip_processing_suffixes("Corin Waverly - POV Beta (1080)") == (
            "Corin Waverly - POV Beta (1080)"
        )

    def test_mid_name_tokens_are_not_suffixes(self):
        # The stem must actually carry a model token mid-name, or this is the
        # plain-stem case again -- the old fixture held no token at all, so the
        # end-anchoring this test is named for was never reached.
        assert strip_processing_suffixes("clip_iris2_scene") == "clip_iris2_scene"


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
    by len, regex-strip, membership in a suffix tuple.
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

    def test_the_suffix_tuple_is_built_from_the_same_constant(self):
        assert UPSCALE_SUFFIX in strip_processing_suffixes.__globals__["PROCESSING_SUFFIXES"]
        assert f"{UPSCALE_SUFFIX}_cfr" in strip_processing_suffixes.__globals__["PROCESSING_SUFFIXES"]


def _string_constants(tree: ast.AST):
    """Every string literal in *tree* except the docstrings.

    Docstrings name the convention in prose all over the repo, and should:
    what must not be spread around is the rule as something code acts on.
    """
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            yield node


class TestOnlyOneModuleSpellsIt:
    def test_the_suffix_is_a_literal_in_exactly_one_place(self):
        offenders = []
        for name in product_sources(PROJECT_ROOT):
            if name == "util/variants.py":
                continue
            tree = ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
            offenders += [
                f"{name}:{node.lineno}" for node in _string_constants(tree)
                if UPSCALE_SUFFIX in node.value
            ]

        assert offenders == [], (
            "the upscale naming rule belongs to util.variants -- use "
            "upscaled_stem, sorted_stem_of or is_upscaled_stem"
        )
