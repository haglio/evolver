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
