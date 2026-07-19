import unittest

from util.variants import is_processed_stem, strip_processing_suffixes


class TestStripProcessingSuffixes(unittest.TestCase):
    def test_strips_single_model_suffix(self):
        self.assertEqual(strip_processing_suffixes("clip_iris2"), "clip")

    def test_strips_composite_model_chains(self):
        self.assertEqual(strip_processing_suffixes("clip_apo8_iris2"), "clip")
        self.assertEqual(strip_processing_suffixes("clip_apo8_prob4"), "clip")
        self.assertEqual(strip_processing_suffixes("clip_apo8_ghq5"), "clip")
        self.assertEqual(strip_processing_suffixes("clip_apo8_gcg5_topaz"), "clip")
        self.assertEqual(strip_processing_suffixes("clip_apo8_gcg5_topaz_cfr"), "clip")

    def test_plain_stem_unchanged(self):
        self.assertEqual(
            strip_processing_suffixes("Nicole Aniston - POV Beta (1080)"),
            "Nicole Aniston - POV Beta (1080)",
        )

    def test_mid_name_tokens_are_not_suffixes(self):
        self.assertEqual(
            strip_processing_suffixes("redacted_redacted"),
            "redacted_redacted",
        )


class TestIsProcessedStem(unittest.TestCase):
    def test_true_when_a_suffix_is_present(self):
        self.assertTrue(is_processed_stem("clip_apo8_iris2"))

    def test_false_for_plain_stem(self):
        self.assertFalse(is_processed_stem("clip"))


if __name__ == "__main__":
    unittest.main()
