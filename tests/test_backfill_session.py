import random
import unittest
from pathlib import Path
from unittest.mock import patch

from backfill.queue import BackfillQueue
from backfill.session import BackfillSession


def _run_now(task):
    """Stand-in for the window's thread pool: run the file work immediately."""
    task()


class TestBackfillSession(unittest.TestCase):
    def _session(self, count=3):
        videos = [Path(f"clip{i}.mp4") for i in range(count)]
        queue = BackfillQueue(videos, rng=random.Random(0))
        return BackfillSession(queue, run_in_background=_run_now)

    def test_an_act_records_the_action_against_the_clip_on_screen(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action") as record:
            outcome = session.apply("side gamma")

        record.assert_called_once_with(clip, "Side Gamma")
        self.assertEqual(outcome, "Side Gamma")

    def test_an_act_retires_the_clip(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action"):
            session.apply("dance")

        self.assertEqual(session.remaining, 2)
        self.assertNotEqual(session.current, clip)

    def test_skip_defers_the_clip_without_touching_the_disk(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.discard_as_weird") as discard:
            outcome = session.apply("skip")

        record.assert_not_called()
        discard.assert_not_called()
        self.assertEqual(outcome, "Skipped")
        self.assertEqual(session.remaining, 3)
        self.assertNotEqual(session.current, clip)

    def test_weird_discards_the_clip_and_writes_no_metadata(self):
        session = self._session()
        clip = session.current

        with patch("backfill.session.record_action") as record, \
             patch("backfill.session.discard_as_weird") as discard:
            outcome = session.apply("trash")

        discard.assert_called_once_with(clip)
        record.assert_not_called()
        self.assertEqual(outcome, "Weird")
        self.assertEqual(session.remaining, 2)

    def test_an_unknown_phrase_leaves_the_clip_on_screen(self):
        session = self._session()
        clip = session.current

        outcome = session.apply("banana")

        self.assertIsNone(outcome)
        self.assertEqual(session.current, clip)
        self.assertEqual(session.remaining, 3)

    def test_a_phrase_heard_after_the_last_clip_does_nothing(self):
        session = self._session(count=1)

        with patch("backfill.session.record_action"):
            session.apply("dance")
            outcome = session.apply("dance")

        self.assertIsNone(outcome)
        self.assertIsNone(session.current)

    def test_the_clip_advances_before_the_file_work_runs(self):
        submitted = []
        videos = [Path(f"clip{i}.mp4") for i in range(3)]
        session = BackfillSession(
            BackfillQueue(videos, rng=random.Random(0)), run_in_background=submitted.append
        )
        clip = session.current

        with patch("backfill.session.record_action") as record:
            session.apply("dance")

            record.assert_not_called()
            self.assertNotEqual(session.current, clip)

            submitted[0]()
            record.assert_called_once_with(clip, "Dancing")


if __name__ == "__main__":
    unittest.main()
