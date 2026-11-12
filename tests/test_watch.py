from __future__ import annotations

import unittest

from util import watch


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
