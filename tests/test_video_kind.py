from __future__ import annotations

import unittest

import pytest
from app_support.video_kind import EXCERPT, FULL_LENGTH

from util import orientation, video_kind


class TestRecording(unittest.TestCase):
    def test_stamping_keeps_the_rest_of_the_block_and_the_payload(self):
        payload = {"video": {"action": "Alpha"}, "version": {"group": "g"}}

        stamped = video_kind.stamped(payload, EXCERPT)

        assert stamped == {"video": {"action": "Alpha", "type": EXCERPT}, "version": {"group": "g"}}
        assert payload == {"video": {"action": "Alpha"}, "version": {"group": "g"}}

    def test_stamping_a_sidecar_that_has_no_video_block_makes_one(self):
        assert video_kind.stamped({"version": {"group": "g"}}, FULL_LENGTH) == {"version": {"group": "g"}, "video": {"type": FULL_LENGTH}}

    def test_a_kind_outside_the_vocabulary_is_refused(self):
        with pytest.raises(ValueError, match="not a video type: 'medium_length'"):
            video_kind.stamped({}, "medium_length")


class TestTheRunningTime(unittest.TestCase):
    def test_reads_the_running_time_off_the_video_block(self):
        assert video_kind.duration_of({"video": {"duration_seconds": 812.5}}) == 812.5

    def test_a_sidecar_that_records_none_reads_as_nothing_to_go_on(self):
        assert video_kind.duration_of({"video": {"type": EXCERPT}}) is None
        assert video_kind.duration_of({}) is None

    def test_a_running_time_nothing_could_read_as_a_number_is_no_answer(self):
        assert video_kind.duration_of({"video": {"duration_seconds": "long"}}) is None

    def test_timing_keeps_the_rest_of_the_block_and_the_payload(self):
        payload = {"video": {"type": EXCERPT}, "version": {"group": "g"}}

        timed = video_kind.timed(payload, 4)

        assert timed == {"video": {"type": EXCERPT, "duration_seconds": 4.0}, "version": {"group": "g"}}
        assert payload == {"video": {"type": EXCERPT}, "version": {"group": "g"}}

    def test_a_negative_running_time_is_refused(self):
        with pytest.raises(ValueError, match=r"not a running time: -1\.0"):
            video_kind.timed({}, -1.0)


class TestTheOrientation(unittest.TestCase):
    def test_reads_the_orientation_off_the_video_block(self):
        assert video_kind.orientation_of({"video": {"orientation": orientation.PORTRAIT}}) == orientation.PORTRAIT

    def test_a_sidecar_that_records_none_reads_as_nothing(self):
        assert video_kind.orientation_of({"video": {"type": EXCERPT}}) == ""
        assert video_kind.orientation_of({}) == ""

    def test_a_word_that_is_neither_orientation_reads_as_nothing(self):
        assert video_kind.orientation_of({"video": {"orientation": orientation.UNKNOWN}}) == ""

    def test_orienting_keeps_the_rest_of_the_block_and_the_payload(self):
        payload = {"video": {"type": EXCERPT}, "version": {"group": "g"}}

        oriented = video_kind.oriented(payload, orientation.LANDSCAPE)

        assert oriented == {"video": {"type": EXCERPT, "orientation": orientation.LANDSCAPE}, "version": {"group": "g"}}
        assert payload == {"video": {"type": EXCERPT}, "version": {"group": "g"}}

    def test_the_third_answer_is_never_written_down(self):
        with pytest.raises(ValueError, match="not an orientation: 'unknown'"):
            video_kind.oriented({}, orientation.UNKNOWN)


