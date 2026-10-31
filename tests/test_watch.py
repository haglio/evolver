"""The watch block: both apps' viewing summed on a sidecar, and its weight."""
from __future__ import annotations

import unittest

from util import watch


class TestWeightFor(unittest.TestCase):
    def test_a_video_nothing_has_watched_weighs_one(self):
        assert watch.weight_for(None) == 1.0
        assert watch.weight_for({}) == 1.0

    def test_three_completions_double_the_weight_and_three_skips_halve_it(self):
        assert watch.weight_for({"completions": 3}) == 2.0
        assert watch.weight_for({"skips": 3}) == 0.5

    def test_one_lock_outweighs_one_completion(self):
        assert watch.weight_for({"locks": 1}) > watch.weight_for({"completions": 1})

    def test_the_weight_is_clamped_to_an_eighth_and_eightfold(self):
        assert watch.weight_for({"completions": 100, "locks": 50}) == 8.0
        assert watch.weight_for({"skips": 100}) == 0.125


class TestAddCounts(unittest.TestCase):
    def test_sums_each_field_across_sources_reading_absent_as_zero(self):
        assert watch.add_counts({"completions": 2, "locks": 1}, None, {"completions": 1, "skips": 4}) == {"completions": 3, "skips": 4, "locks": 1}


class TestStamped(unittest.TestCase):
    def test_records_the_counts_and_their_weight_beside_the_rest(self):
        payload = {"video": {"type": "short"}}

        stamped = watch.stamped(payload, {"completions": 3, "skips": 0, "locks": 0})

        assert stamped == {"video": {"type": "short"}, "watch": {"completions": 3, "skips": 0, "locks": 0, "weight": 2.0}}
        assert payload == {"video": {"type": "short"}}

    def test_a_video_nothing_has_watched_carries_no_block(self):
        payload = {"video": {"type": "short"}, "watch": {"completions": 1, "skips": 0, "locks": 0, "weight": 1.26}}

        stamped = watch.stamped(payload, {"completions": 0, "skips": 0, "locks": 0})

        assert stamped == {"video": {"type": "short"}}

    def test_a_favorite_is_left_as_the_apps_that_mark_it_marked_it(self):
        favorite = {"video": {}, "favorite": True, "web_url": "https://example.com/gallery/101"}

        assert watch.stamped(favorite, {}) == favorite
