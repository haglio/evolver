from __future__ import annotations

import inspect
import unittest

import pytest
from app_support.video_kind import EXCERPT, FULL_LENGTH

from util import orientation, provenance, video_kind


class TestRecording(unittest.TestCase):
    def test_short_is_no_longer_a_kind_a_sidecar_can_hold(self):
        assert video_kind.kind_of({"video": {"type": "short"}}) == ""

    def test_reads_the_kind_off_the_video_block(self):
        payload = {"video": {"action": "Alpha", "type": EXCERPT}}
        assert video_kind.kind_of(payload) == EXCERPT

    def test_a_sidecar_written_before_the_field_existed_reads_as_nothing(self):
        assert video_kind.kind_of({"video": {"action": "Alpha"}}) == ""
        assert video_kind.kind_of({}) == ""

    def test_a_kind_nothing_recognizes_reads_as_nothing(self):
        assert video_kind.kind_of({"video": {"type": "medium_length"}}) == ""

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


_A_VALUE_EACH_WRITER_TAKES = {"stamped": EXCERPT, "timed": 4.0, "oriented": orientation.PORTRAIT}


def _the_writers_video_kind_has() -> set[str]:
    return {name for name, function in inspect.getmembers(video_kind, inspect.isfunction)
            if function.__module__ == video_kind.__name__ and not name.startswith("_")
            and inspect.signature(function).return_annotation == "dict"}


class TestTellingABareSidecarApart(unittest.TestCase):
    def test_every_writer_here_leaves_a_record_bare(self):
        assert _the_writers_video_kind_has() == set(_A_VALUE_EACH_WRITER_TAKES), "a new writer: give it a value here and list its field among _OWN_FIELDS"
        for writer, value in _A_VALUE_EACH_WRITER_TAKES.items():
            with self.subTest(writer=writer):
                assert video_kind.only_the_video_itself(getattr(video_kind, writer)({}, value)), "a field this module writes must not turn a bare record into evidence"

    def test_a_sidecar_holding_only_a_kind_records_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": EXCERPT}})

    def test_a_sidecar_holding_a_kind_and_a_running_time_records_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": EXCERPT, "duration_seconds": 4.0}})

    def test_a_sidecar_holding_its_orientation_beside_them_records_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": EXCERPT, "duration_seconds": 4.0, "orientation": orientation.PORTRAIT}})

    def test_the_viewing_stamped_beside_them_is_still_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": EXCERPT}, "watch": {"completions": 2, "skips": 0, "locks": 0, "weight": 1.5874}})

    def test_a_favorite_marked_beside_them_with_its_page_is_still_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": EXCERPT}, "favorite": True, "web_url": "https://example.com/gallery/101"})

    def test_a_record_of_what_made_the_file_beside_them_is_still_nothing_else(self):
        assert video_kind.only_the_video_itself({"video": {"type": EXCERPT}, provenance.BLOCK: {"upscale": provenance.reconstructed("evolver")}}), "a scrape that took the stamp for its own work would never fetch the clip's prompts"

    def test_a_provenance_stamp_alone_is_nothing_else(self):
        assert video_kind.only_the_video_itself({provenance.BLOCK: {"upscale": provenance.reconstructed("evolver")}}), "an upscale is stamped as it is written, before its scrape or its kind lands"

    def test_an_empty_record_is_something_else(self):
        assert not video_kind.only_the_video_itself({}), "an unreadable record reads empty too"

    def test_a_generation_beside_them_is_something_else(self):
        assert not video_kind.only_the_video_itself({"video": {"type": EXCERPT, "prompt": "a prompt"}})

    def test_a_block_of_its_own_beside_them_is_something_else(self):
        assert not video_kind.only_the_video_itself({"video": {"type": EXCERPT}, "clip": {"index": 1}})
