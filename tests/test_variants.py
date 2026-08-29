from util.variants import is_processed_stem, strip_processing_suffixes


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
