from __future__ import annotations

import unittest

import pytest

from util import orientation, provenance, video_kind


class TestClassify(unittest.TestCase):
    def test_a_short_running_clip_is_a_short(self):
        assert video_kind.classify(genau=False, clip=False, duration_seconds=4.0) == video_kind.SHORT

    def test_a_long_running_clip_is_full_length(self):
        assert video_kind.classify(genau=False, clip=False, duration_seconds=900.0) == video_kind.FULL_LENGTH

    def test_an_unknown_running_time_reads_as_full_length(self):
        assert video_kind.classify(genau=False, clip=False, duration_seconds=None) == video_kind.FULL_LENGTH

    def test_a_carved_excerpt_outranks_its_running_time(self):
        assert video_kind.classify(genau=False, clip=True, duration_seconds=4.0) == video_kind.CLIP

    def test_a_genau_flick_outranks_everything_else(self):
        assert video_kind.classify(genau=True, clip=True, duration_seconds=900.0) == video_kind.GENAU_FLICK

    def test_the_boundary_second_still_counts_as_short(self):
        assert video_kind.classify(genau=False, clip=False, duration_seconds=video_kind.SHORT_MAX_SECONDS) == video_kind.SHORT


class TestRecording(unittest.TestCase):
    def test_reads_the_kind_off_the_video_block(self):
        payload = {"video": {"action": "Alpha", "type": video_kind.CLIP}}
        assert video_kind.kind_of(payload) == video_kind.CLIP

    def test_a_sidecar_written_before_the_field_existed_reads_as_nothing(self):
        assert video_kind.kind_of({"video": {"action": "Alpha"}}) == ""
        assert video_kind.kind_of({}) == ""

    def test_a_kind_nothing_recognizes_reads_as_nothing(self):
        assert video_kind.kind_of({"video": {"type": "medium_length"}}) == ""

    def test_stamping_keeps_the_rest_of_the_block_and_the_payload(self):
        payload = {"video": {"action": "Alpha"}, "version": {"group": "g"}}

        stamped = video_kind.stamped(payload, video_kind.SHORT)

        assert stamped == {"video": {"action": "Alpha", "type": video_kind.SHORT}, "version": {"group": "g"}}
        assert payload == {"video": {"action": "Alpha"}, "version": {"group": "g"}}

    def test_stamping_a_sidecar_that_has_no_video_block_makes_one(self):
        assert video_kind.stamped({"version": {"group": "g"}}, video_kind.FULL_LENGTH) == {"version": {"group": "g"}, "video": {"type": video_kind.FULL_LENGTH}}

    def test_a_kind_outside_the_vocabulary_is_refused(self):
        with pytest.raises(ValueError, match="not a video type: 'medium_length'"):
            video_kind.stamped({}, "medium_length")


class TestTheRunningTime(unittest.TestCase):
    def test_reads_the_running_time_off_the_video_block(self):
        assert video_kind.duration_of({"video": {"duration_seconds": 812.5}}) == 812.5

    def test_a_sidecar_that_records_none_reads_as_nothing_to_go_on(self):
        assert video_kind.duration_of({"video": {"type": video_kind.SHORT}}) is None
        assert video_kind.duration_of({}) is None

    def test_a_running_time_nothing_could_read_as_a_number_is_no_answer(self):
        assert video_kind.duration_of({"video": {"duration_seconds": "long"}}) is None

    def test_timing_keeps_the_rest_of_the_block_and_the_payload(self):
        payload = {"video": {"type": video_kind.SHORT}, "version": {"group": "g"}}

        timed = video_kind.timed(payload, 4)

        assert timed == {"video": {"type": video_kind.SHORT, "duration_seconds": 4.0}, "version": {"group": "g"}}
        assert payload == {"video": {"type": video_kind.SHORT}, "version": {"group": "g"}}

    def test_a_negative_running_time_is_refused(self):
        with pytest.raises(ValueError, match=r"not a running time: -1\.0"):
            video_kind.timed({}, -1.0)


class TestTheOrientation(unittest.TestCase):
    def test_reads_the_orientation_off_the_video_block(self):
        assert video_kind.orientation_of({"video": {"orientation": orientation.PORTRAIT}}) == orientation.PORTRAIT

    def test_a_sidecar_that_records_none_reads_as_nothing(self):
        assert video_kind.orientation_of({"video": {"type": video_kind.SHORT}}) == ""
        assert video_kind.orientation_of({}) == ""

    def test_a_word_that_is_neither_orientation_reads_as_nothing(self):
        assert video_kind.orientation_of({"video": {"orientation": orientation.UNKNOWN}}) == ""

    def test_orienting_keeps_the_rest_of_the_block_and_the_payload(self):
        payload = {"video": {"type": video_kind.SHORT}, "version": {"group": "g"}}

        oriented = video_kind.oriented(payload, orientation.LANDSCAPE)

        assert oriented == {"video": {"type": video_kind.SHORT, "orientation": orientation.LANDSCAPE}, "version": {"group": "g"}}
        assert payload == {"video": {"type": video_kind.SHORT}, "version": {"group": "g"}}

    def test_the_third_answer_is_never_written_down(self):
        with pytest.raises(ValueError, match="not an orientation: 'unknown'"):
            video_kind.oriented({}, orientation.UNKNOWN)


class TestTellingABareSidecarApart(unittest.TestCase):
    def test_a_sidecar_holding_only_a_kind_records_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": video_kind.SHORT}})

    def test_a_sidecar_holding_a_kind_and_a_running_time_records_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": video_kind.SHORT, "duration_seconds": 4.0}})

    def test_a_sidecar_holding_its_orientation_beside_them_records_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": video_kind.SHORT, "duration_seconds": 4.0, "orientation": orientation.PORTRAIT}})

    def test_the_viewing_stamped_beside_them_is_still_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": video_kind.SHORT}, "watch": {"completions": 2, "skips": 0, "locks": 0, "weight": 1.5874}})

    def test_a_favorite_marked_beside_them_with_its_page_is_still_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": video_kind.SHORT}, "favorite": True, "web_url": "https://example.com/gallery/101"})

    def test_a_record_of_what_made_the_file_beside_them_is_still_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": video_kind.SHORT}, provenance.BLOCK: {"upscale": provenance.reconstructed("evolver")}})

    def test_a_record_of_what_made_the_file_on_its_own_is_nothing_else_either(self):
        assert video_kind.only_the_video_itself({provenance.BLOCK: {"upscale": provenance.reconstructed("evolver")}})

    def test_a_generation_beside_them_is_something_else(self):
        assert not video_kind.only_the_video_itself({"video": {"type": video_kind.SHORT, "prompt": "a prompt"}})

    def test_a_block_of_its_own_beside_them_is_something_else(self):
        assert not video_kind.only_the_video_itself({"video": {"type": video_kind.SHORT}, "clip": {"index": 1}})
