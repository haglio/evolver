from __future__ import annotations

from util.version_groups import group_ids, group_key_tokens


class TestGroupKeyTokens:
    def test_strips_processing_suffixes_and_tokenizes(self):
        assert group_key_tokens("Scene-Name_apo8_iris2") == ("scene", "name")

    def test_keeps_a_manual_tag_the_plain_strip_leaves(self):
        assert group_key_tokens("Jane-Doe-lA0JUsAd_3_apf2_iris2") == (
            "jane", "doe", "la0jusad", "3",
        )


class TestGroupIds:
    def test_clean_topaz_version_shares_the_originals_id(self):
        ids = group_ids(["scene", "scene_apo8_iris2"])
        assert ids["scene_apo8_iris2"] == ids["scene"]
        assert ids["scene"] == "scene"

    def test_hand_made_version_with_extra_tag_still_folds(self):
        ids = group_ids(["Jane-Doe-lA0JUsAd", "Jane-Doe-lA0JUsAd_3_apf2_iris2"])
        assert ids["Jane-Doe-lA0JUsAd_3_apf2_iris2"] == ids["Jane-Doe-lA0JUsAd"]
        assert ids["Jane-Doe-lA0JUsAd"] == "Jane-Doe-lA0JUsAd"

    def test_different_numbered_scenes_stay_separate(self):
        ids = group_ids(["Ada-Roe-1", "Ada-Roe-2"])
        assert ids["Ada-Roe-1"] != ids["Ada-Roe-2"]

    def test_singleton_maps_to_its_own_id(self):
        assert group_ids(["solo"]) == {"solo": "solo"}

    def test_an_override_folds_a_stem_the_name_rule_cannot_reach(self):
        stems = ["Petra-Vance_540-xq3k9v2w", "Petra Vance Beta Cut 4k 60fps"]

        ids = group_ids(stems, {"Petra Vance Beta Cut 4k 60fps": "Petra-Vance_540-xq3k9v2w"})

        assert ids["Petra Vance Beta Cut 4k 60fps"] == ids["Petra-Vance_540-xq3k9v2w"]
        assert ids["Petra-Vance_540-xq3k9v2w"] == "Petra-Vance_540-xq3k9v2w"

    def test_an_override_still_holds_once_either_side_has_been_upscaled(self):
        declared = {"Petra Vance Beta Cut 4k 60fps": "Petra-Vance_540-xq3k9v2w"}
        for stems in (
            ["Petra-Vance_540-xq3k9v2w_apo8_iris2", "Petra Vance Beta Cut 4k 60fps"],
            ["Petra-Vance_540-xq3k9v2w", "Petra Vance Beta Cut 4k 60fps_apo8_iris2"],
            ["Petra-Vance_540-xq3k9v2w_apo8_iris2", "Petra Vance Beta Cut 4k 60fps_apo8_iris2",
             "Petra Vance Beta Cut 4k 60fps"],
        ):
            ids = group_ids(stems, declared)

            assert set(ids.values()) == {"Petra-Vance_540-xq3k9v2w"}, stems

    def test_a_scene_named_past_another_is_not_a_version_of_it(self):
        stems = ["Jane Doe", "Jane Doe - Cut to Length", "Jane-Doe-&-Ada-Roe-b4t7k1qz"]

        ids = group_ids(stems)

        assert len(set(ids.values())) == 3

    def test_a_second_download_of_one_video_keeps_its_family(self):
        stems = ["Jane Doe - Scene Two", "Jane Doe - Scene Two (2)",
                 "Jane Doe - Scene Two (3)_apo8_iris2"]

        ids = group_ids(stems)

        assert len(set(ids.values())) == 1

    def test_a_hand_trimmed_cut_stays_with_the_video_it_came_from(self):
        stems = ["Jane Doe 4471_720p", "Jane Doe 4471_720p - trimmed_2_apo8_iris2"]

        ids = group_ids(stems)

        assert len(set(ids.values())) == 1

    def test_three_scenes_each_with_a_version_form_three_families(self):
        stems = []
        for n in (1, 2, 3):
            stems += [f"clip-{n}", f"clip-{n}_apo8_iris2"]
        ids = group_ids(stems)
        assert len(set(ids.values())) == 3
        for n in (1, 2, 3):
            assert ids[f"clip-{n}_apo8_iris2"] == ids[f"clip-{n}"]
