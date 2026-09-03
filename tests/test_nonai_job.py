"""The three JSON files the non-AI upscale stage keeps its state in.

Every function here takes the file it works on, so this module reads no
``config`` at all and a test needs nothing but a temp directory — which is the
point of the seam: the stage's persistence used to be reachable only by
constructing the whole stage and steering it with ``override_config``.
"""

import json
import time
import unittest

from tests.temp_helpers import workspace_temp_dir
from util import nonai_job


class TestJobRecord(unittest.TestCase):
    def test_a_saved_job_reads_back_with_the_keys_it_was_given(self):
        """The file is the on-disk contract with a live multi-hour encode, so
        the record round-trips unchanged rather than through any schema."""
        with workspace_temp_dir() as root:
            path = root / "state" / "job.json"
            job = {"pid": 4242, "source": "larkin/0 unsorted/a.mp4", "suspended": False}

            nonai_job.save_job(path, job)

            self.assertEqual(nonai_job.load_job(path), job)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), job)

    def test_saving_creates_the_state_directory(self):
        with workspace_temp_dir() as root:
            path = root / "not" / "yet" / "job.json"

            nonai_job.save_job(path, {"pid": 1})

            self.assertTrue(path.is_file())

    def test_no_file_means_no_job(self):
        with workspace_temp_dir() as root:
            self.assertIsNone(nonai_job.load_job(root / "job.json"))

    def test_an_unreadable_job_file_means_no_job(self):
        """The sync service covering the project tree can rename or truncate the
        file mid-encode; a half-written record must not crash the tick."""
        with workspace_temp_dir() as root:
            path = root / "job.json"
            path.write_text('{"pid": 42', encoding="utf-8")

            self.assertIsNone(nonai_job.load_job(path))

    def test_a_job_file_holding_something_other_than_a_record_means_no_job(self):
        with workspace_temp_dir() as root:
            path = root / "job.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")

            self.assertIsNone(nonai_job.load_job(path))

    def test_clearing_removes_the_file_and_tolerates_it_being_gone(self):
        with workspace_temp_dir() as root:
            path = root / "job.json"
            nonai_job.save_job(path, {"pid": 1})

            nonai_job.clear_job(path)
            nonai_job.clear_job(path)

            self.assertFalse(path.exists())


class TestAttempts(unittest.TestCase):
    def test_a_key_with_no_record_has_no_attempts(self):
        with workspace_temp_dir() as root:
            self.assertEqual(nonai_job.attempts_of(root / "a.json", "larkin/a.mp4"), 0)

    def test_bumping_counts_per_key(self):
        with workspace_temp_dir() as root:
            path = root / "state" / "attempts.json"

            nonai_job.bump_attempts(path, "larkin/a.mp4")
            nonai_job.bump_attempts(path, "larkin/a.mp4")
            nonai_job.bump_attempts(path, "other/b.mp4")

            self.assertEqual(nonai_job.attempts_of(path, "larkin/a.mp4"), 2)
            self.assertEqual(nonai_job.attempts_of(path, "other/b.mp4"), 1)

    def test_clearing_one_key_leaves_the_others(self):
        with workspace_temp_dir() as root:
            path = root / "attempts.json"
            nonai_job.bump_attempts(path, "larkin/a.mp4")
            nonai_job.bump_attempts(path, "other/b.mp4")

            nonai_job.clear_attempts(path, "larkin/a.mp4")

            self.assertEqual(nonai_job.attempts_of(path, "larkin/a.mp4"), 0)
            self.assertEqual(nonai_job.attempts_of(path, "other/b.mp4"), 1)

    def test_clearing_a_key_that_was_never_counted_writes_nothing(self):
        """The counter is cleared on every stop, most of which never counted the
        clip, so the common case must not touch the disk."""
        with workspace_temp_dir() as root:
            path = root / "attempts.json"

            nonai_job.clear_attempts(path, "larkin/a.mp4")

            self.assertFalse(path.exists())

    def test_an_unreadable_attempts_file_counts_as_empty(self):
        with workspace_temp_dir() as root:
            path = root / "attempts.json"
            path.write_text("not json", encoding="utf-8")

            self.assertEqual(nonai_job.attempts_of(path, "larkin/a.mp4"), 0)


class TestCooldown(unittest.TestCase):
    def test_no_stamp_means_the_epoch(self):
        with workspace_temp_dir() as root:
            self.assertEqual(nonai_job.last_encode_ended_at(root / "cooldown.json"), 0.0)

    def test_a_stamp_reads_back_as_the_moment_it_was_written(self):
        with workspace_temp_dir() as root:
            path = root / "state" / "cooldown.json"
            before = time.time()

            nonai_job.stamp_encode_ended(path)

            stamped = nonai_job.last_encode_ended_at(path)
            self.assertGreaterEqual(stamped, before)
            self.assertLessEqual(stamped, time.time())
            self.assertEqual(
                set(json.loads(path.read_text(encoding="utf-8"))), {"ended_at"}
            )

    def test_a_stamp_that_is_not_a_number_reads_as_the_epoch(self):
        with workspace_temp_dir() as root:
            path = root / "cooldown.json"
            path.write_text('{"ended_at": "yesterday"}', encoding="utf-8")

            self.assertEqual(nonai_job.last_encode_ended_at(path), 0.0)

    def test_a_cooldown_file_holding_something_else_reads_as_the_epoch(self):
        with workspace_temp_dir() as root:
            path = root / "cooldown.json"
            path.write_text('"nope"', encoding="utf-8")

            self.assertEqual(nonai_job.last_encode_ended_at(path), 0.0)


if __name__ == "__main__":
    unittest.main()
