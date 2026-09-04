"""The watch block: both apps' viewing summed on a sidecar, and its weight."""

import unittest

from util import watch


class TestWeightFor(unittest.TestCase):
    def test_a_video_nothing_has_watched_weighs_one(self):
        self.assertEqual(watch.weight_for(None), 1.0)
        self.assertEqual(watch.weight_for({}), 1.0)

    def test_three_completions_double_the_weight_and_three_skips_halve_it(self):
        self.assertEqual(watch.weight_for({"completions": 3}), 2.0)
        self.assertEqual(watch.weight_for({"skips": 3}), 0.5)

    def test_one_lock_outweighs_one_completion(self):
        self.assertGreater(watch.weight_for({"locks": 1}), watch.weight_for({"completions": 1}))

    def test_the_weight_is_clamped_to_an_eighth_and_eightfold(self):
        self.assertEqual(watch.weight_for({"completions": 100, "locks": 50}), 8.0)
        self.assertEqual(watch.weight_for({"skips": 100}), 0.125)


class TestAddCounts(unittest.TestCase):
    def test_sums_each_field_across_sources_reading_absent_as_zero(self):
        self.assertEqual(
            watch.add_counts({"completions": 2, "locks": 1}, None, {"completions": 1, "skips": 4}),
            {"completions": 3, "skips": 4, "locks": 1},
        )


class TestStamped(unittest.TestCase):
    def test_records_the_counts_and_their_weight_beside_the_rest(self):
        payload = {"video": {"type": "short"}}

        stamped = watch.stamped(payload, {"completions": 3, "skips": 0, "locks": 0}, favorite=False)

        self.assertEqual(stamped, {
            "video": {"type": "short"},
            "watch": {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0},
        })
        self.assertEqual(payload, {"video": {"type": "short"}})

    def test_a_video_nothing_has_watched_carries_no_block(self):
        payload = {"video": {"type": "short"}, "watch": {"completions": 1, "skips": 0, "locks": 0, "weight": 1.26}}

        stamped = watch.stamped(payload, {"completions": 0, "skips": 0, "locks": 0}, favorite=False)

        self.assertEqual(stamped, {"video": {"type": "short"}})

    def test_a_favorite_is_flagged_and_loses_the_flag_when_it_stops_being_one(self):
        flagged = watch.stamped({"video": {}}, {}, favorite=True)
        self.assertIs(flagged["favorite"], True)

        self.assertNotIn("favorite", watch.stamped(flagged, {}, favorite=False))
