import unittest

from util.version_groups import group_ids, group_key_tokens


class TestGroupKeyTokens(unittest.TestCase):
    def test_strips_processing_suffixes_and_tokenizes(self):
        self.assertEqual(group_key_tokens("Scene-Name_apo8_iris2"), ("scene", "name"))

    def test_keeps_a_manual_tag_the_plain_strip_leaves(self):
        # "_3" is not a known Topaz suffix, so it survives the strip and rides
        # along as a trailing token — still a prefix of nothing shorter.
        self.assertEqual(
            group_key_tokens("Mya-Luanna-lA0JUsAd_3_apf2_iris2"),
            ("mya", "luanna", "la0jusad", "3"),
        )


class TestGroupIds(unittest.TestCase):
    def test_clean_topaz_variant_shares_the_originals_id(self):
        ids = group_ids(["scene", "scene_apo8_iris2"])
        self.assertEqual(ids["scene_apo8_iris2"], ids["scene"])
        self.assertEqual(ids["scene"], "scene")

    def test_hand_made_variant_with_extra_tag_still_folds(self):
        ids = group_ids(["Mya-Luanna-lA0JUsAd", "Mya-Luanna-lA0JUsAd_3_apf2_iris2"])
        self.assertEqual(
            ids["Mya-Luanna-lA0JUsAd_3_apf2_iris2"], ids["Mya-Luanna-lA0JUsAd"]
        )
        self.assertEqual(ids["Mya-Luanna-lA0JUsAd"], "Mya-Luanna-lA0JUsAd")

    def test_different_numbered_scenes_stay_separate(self):
        ids = group_ids(["Juelz-Ventura-1", "Juelz-Ventura-2"])
        self.assertNotEqual(ids["Juelz-Ventura-1"], ids["Juelz-Ventura-2"])

    def test_singleton_maps_to_its_own_id(self):
        self.assertEqual(group_ids(["solo"]), {"solo": "solo"})

    def test_an_override_folds_a_stem_the_name_rule_cannot_reach(self):
        """A hand-renamed trim shares no name prefix with the video it came from
        — "redacted POV BJ 4k 60fps" against "redacted_540-hash" —
        so the only way to call them one video is to say so."""
        stems = ["redacted_540-pacI21CK", "redacted POV BJ 4k 60fps"]

        ids = group_ids(stems, {"redacted POV BJ 4k 60fps": "redacted_540-pacI21CK"})

        self.assertEqual(ids["redacted POV BJ 4k 60fps"], ids["redacted_540-pacI21CK"])
        self.assertEqual(ids["redacted_540-pacI21CK"], "redacted_540-pacI21CK")

    def test_three_scenes_each_with_a_variant_form_three_families(self):
        stems = []
        for n in (1, 2, 3):
            stems += [f"clip-{n}", f"clip-{n}_apo8_iris2"]
        ids = group_ids(stems)
        self.assertEqual(len(set(ids.values())), 3)
        for n in (1, 2, 3):
            self.assertEqual(ids[f"clip-{n}_apo8_iris2"], ids[f"clip-{n}"])


if __name__ == "__main__":
    unittest.main()
