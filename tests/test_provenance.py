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

    def test_a_record_with_no_stamps_or_a_malformed_block_records_none(self):
        assert provenance.stamps_of({}) == {}
        assert provenance.stamps_of({provenance.BLOCK: "text"}) == {}


if __name__ == "__main__":
    unittest.main()
