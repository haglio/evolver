from __future__ import annotations

import unittest

from app_support import provenance as stamps

from util import provenance


class TestAStampWrittenAfterTheFact(unittest.TestCase):
    def test_has_exactly_the_keys_a_stamp_taken_at_the_time_has(self):
        taken_at_the_time = stamps.stamp("example", anchor=__file__)

        assert set(provenance.reconstructed("example")) == set(taken_at_the_time)


class TestTheStampsOnARecord(unittest.TestCase):
    def test_a_stamp_is_filed_under_its_act_beside_the_others(self):
        payload = provenance.recorded({"title": "scene one"}, "generation", {"app": "alpha"})
        payload = provenance.recorded(payload, "upscale", {"app": "beta"})

        assert provenance.stamps_of(payload) == {"generation": {"app": "alpha"}, "upscale": {"app": "beta"}}
        assert payload["title"] == "scene one"

    def test_recording_one_leaves_the_record_it_was_given_as_it_was(self):
        payload = {"title": "scene one"}

        provenance.recorded(payload, "generation", {"app": "alpha"})

        assert payload == {"title": "scene one"}

    def test_taking_one_away_keeps_the_rest(self):
        payload = provenance.recorded({}, "generation", {"app": "alpha"})
        payload = provenance.recorded(payload, "upscale", {"app": "beta"})

        assert provenance.stamps_of(provenance.without(payload, "generation")) == {"upscale": {"app": "beta"}}

    def test_a_record_with_no_stamps_or_a_malformed_block_records_none(self):
        assert provenance.stamps_of({}) == {}
        assert provenance.stamps_of({provenance.BLOCK: "text"}) == {}

    def test_where_both_records_stamp_the_same_act_the_later_one_stands(self):
        earlier = provenance.recorded({}, "generation", {"app": "alpha"})
        earlier = provenance.recorded(earlier, "upscale", {"app": "beta"})
        later = provenance.recorded({"title": "scene one"}, "generation", {"app": "gamma"})

        carried = provenance.carried_forward(earlier, later)

        assert provenance.stamps_of(carried) == {"generation": {"app": "gamma"}, "upscale": {"app": "beta"}}
        assert carried["title"] == "scene one"

    def test_carrying_forward_between_records_with_no_stamps_adds_no_block(self):
        assert provenance.carried_forward({}, {"title": "scene one"}) == {"title": "scene one"}


if __name__ == "__main__":
    unittest.main()
