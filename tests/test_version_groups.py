import unittest

from util.version_groups import group_ids, group_key_tokens


class TestGroupKeyTokens(unittest.TestCase):
    def test_strips_processing_suffixes_and_tokenizes(self):
        self.assertEqual(group_key_tokens("Scene-Name_apo8_iris2"), ("scene", "name"))

    def test_keeps_a_manual_tag_the_plain_strip_leaves(self):
        # "_3" is not a known Topaz suffix, so it survives the strip and rides
        # along as a trailing token — still a prefix of nothing shorter.
        self.assertEqual(
            group_key_tokens("Jane Doe-lA0JUsAd_3_apf2_iris2"),
            ("mya", "luanna", "la0jusad", "3"),
        )


class TestGroupIds(unittest.TestCase):
    def test_clean_topaz_variant_shares_the_originals_id(self):
        ids = group_ids(["scene", "scene_apo8_iris2"])
        self.assertEqual(ids["scene_apo8_iris2"], ids["scene"])
        self.assertEqual(ids["scene"], "scene")

    def test_hand_made_variant_with_extra_tag_still_folds(self):
        ids = group_ids(["Jane Doe-lA0JUsAd", "Jane Doe-lA0JUsAd_3_apf2_iris2"])
        self.assertEqual(
            ids["Jane Doe-lA0JUsAd_3_apf2_iris2"], ids["Jane Doe-lA0JUsAd"]
        )
        self.assertEqual(ids["Jane Doe-lA0JUsAd"], "Jane Doe-lA0JUsAd")

    def test_different_numbered_scenes_stay_separate(self):
        ids = group_ids(["Ada Roe-1", "Ada Roe-2"])
        self.assertNotEqual(ids["Ada Roe-1"], ids["Ada Roe-2"])

    def test_singleton_maps_to_its_own_id(self):
        self.assertEqual(group_ids(["solo"]), {"solo": "solo"})

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
