import unittest

from util import video_type


class TestClassify(unittest.TestCase):
    def test_a_short_running_clip_is_a_short(self):
        self.assertEqual(
            video_type.classify(genau=False, excerpt=False, duration_seconds=4.0),
            video_type.SHORT,
        )

    def test_a_long_running_clip_is_full_length(self):
        self.assertEqual(
            video_type.classify(genau=False, excerpt=False, duration_seconds=900.0),
            video_type.FULL_LENGTH,
        )

    def test_an_unknown_running_time_reads_as_full_length(self):
        self.assertEqual(
            video_type.classify(genau=False, excerpt=False, duration_seconds=None),
            video_type.FULL_LENGTH,
        )

    def test_a_carved_excerpt_outranks_its_running_time(self):
        self.assertEqual(
            video_type.classify(genau=False, excerpt=True, duration_seconds=4.0),
            video_type.EXCERPT,
        )

    def test_a_genau_loop_outranks_everything_else(self):
        self.assertEqual(
            video_type.classify(genau=True, excerpt=True, duration_seconds=900.0),
            video_type.GENAU_CLIP,
        )

    def test_the_boundary_second_still_counts_as_short(self):
        self.assertEqual(
            video_type.classify(
                genau=False, excerpt=False,
                duration_seconds=video_type.SHORT_MAX_SECONDS,
            ),
            video_type.SHORT,
        )


class TestRecording(unittest.TestCase):
    def test_reads_the_kind_off_the_video_block(self):
        payload = {"video": {"action": "Alpha", "type": video_type.EXCERPT}}
        self.assertEqual(video_type.type_of(payload), video_type.EXCERPT)

    def test_a_sidecar_written_before_the_field_existed_reads_as_nothing(self):
        self.assertEqual(video_type.type_of({"video": {"action": "Alpha"}}), "")
        self.assertEqual(video_type.type_of({}), "")

    def test_a_kind_nothing_recognizes_reads_as_nothing(self):
        self.assertEqual(video_type.type_of({"video": {"type": "medium_length"}}), "")

    def test_stamping_keeps_the_rest_of_the_block_and_the_payload(self):
        payload = {"video": {"action": "Alpha"}, "version": {"group": "g"}}

        stamped = video_type.stamped(payload, video_type.SHORT)

        self.assertEqual(
            stamped,
            {"video": {"action": "Alpha", "type": video_type.SHORT},
             "version": {"group": "g"}},
        )
        self.assertEqual(payload, {"video": {"action": "Alpha"}, "version": {"group": "g"}})

    def test_stamping_a_sidecar_that_has_no_video_block_makes_one(self):
        self.assertEqual(
            video_type.stamped({"version": {"group": "g"}}, video_type.FULL_LENGTH),
            {"version": {"group": "g"}, "video": {"type": video_type.FULL_LENGTH}},
        )

    def test_a_kind_outside_the_vocabulary_is_refused(self):
        with self.assertRaises(ValueError):
            video_type.stamped({}, "medium_length")


class TestTheRunningTime(unittest.TestCase):
    """The measurement the kind is read off, kept beside it."""

    def test_reads_the_running_time_off_the_video_block(self):
        self.assertEqual(
            video_type.duration_of({"video": {"duration_seconds": 812.5}}), 812.5
        )

    def test_a_sidecar_that_records_none_reads_as_nothing_to_go_on(self):
        self.assertIsNone(video_type.duration_of({"video": {"type": video_type.SHORT}}))
        self.assertIsNone(video_type.duration_of({}))

    def test_a_running_time_nothing_could_read_as_a_number_is_no_answer(self):
        self.assertIsNone(video_type.duration_of({"video": {"duration_seconds": "long"}}))

    def test_timing_keeps_the_rest_of_the_block_and_the_payload(self):
        payload = {"video": {"type": video_type.SHORT}, "version": {"group": "g"}}

        timed = video_type.timed(payload, 4)

        self.assertEqual(
            timed,
            {"video": {"type": video_type.SHORT, "duration_seconds": 4.0},
             "version": {"group": "g"}},
        )
        self.assertEqual(payload, {"video": {"type": video_type.SHORT},
                                   "version": {"group": "g"}})

    def test_a_negative_running_time_is_refused(self):
        with self.assertRaises(ValueError):
            video_type.timed({}, -1.0)


class TestTellingABareSidecarApart(unittest.TestCase):
    """Two stages read a sidecar's contents as evidence that something else
    happened to the clip — a scrape, a generation. Everything this module
    records has to stay invisible to them, however many fields that becomes."""

    def test_a_sidecar_holding_only_a_kind_records_nothing_else(self):
        self.assertTrue(
            video_type.only_the_video_itself({"video": {"type": video_type.SHORT}})
        )

    def test_a_sidecar_holding_a_kind_and_a_running_time_records_nothing_else(self):
        self.assertTrue(video_type.only_the_video_itself(
            {"video": {"type": video_type.SHORT, "duration_seconds": 4.0}}
        ))

    def test_the_viewing_stamped_beside_them_is_still_nothing_else(self):
        self.assertTrue(video_type.only_the_video_itself({
            "video": {"type": video_type.SHORT},
            "watch": {"completions": 2, "skips": 0, "locks": 0, "weight": 1.5874},
            "favorite": True,
        }))

    def test_a_generation_beside_them_is_something_else(self):
        self.assertFalse(video_type.only_the_video_itself(
            {"video": {"type": video_type.SHORT, "prompt": "a prompt"}}
        ))

    def test_a_block_of_its_own_beside_them_is_something_else(self):
        self.assertFalse(video_type.only_the_video_itself(
            {"video": {"type": video_type.SHORT}, "clip": {"index": 1}}
        ))
