from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from app_support.testing import process_alive

from tests.temp_helpers import workspace_temp_dir
from util import nonai_job


class TestJobRecord(unittest.TestCase):
    def test_a_saved_job_reads_back_with_the_keys_it_was_given(self):
        with workspace_temp_dir() as root:
            path = root / "state" / "job.json"
            fields = {"pid": 4242, "source": "lagoon/0 unsorted/a.mp4", "suspended": False}

            nonai_job.save_job(path, nonai_job.Job(dict(fields)))

            assert nonai_job.load_job(path).fields() == fields
            assert json.loads(path.read_text(encoding="utf-8")) == fields

    def test_saving_creates_the_state_directory(self):
        with workspace_temp_dir() as root:
            path = root / "not" / "yet" / "job.json"

            nonai_job.save_job(path, nonai_job.Job({"pid": 1}))

            assert path.is_file()

    def test_no_file_means_no_job(self):
        with workspace_temp_dir() as root:
            assert nonai_job.load_job(root / "job.json") is None

    def test_an_unreadable_job_file_means_no_job(self):
        with workspace_temp_dir() as root:
            path = root / "job.json"
            path.write_text('{"pid": 42', encoding="utf-8")

            assert nonai_job.load_job(path) is None

    def test_a_job_file_holding_something_other_than_a_record_means_no_job(self):
        with workspace_temp_dir() as root:
            path = root / "job.json"
            path.write_text("[1, 2, 3]", encoding="utf-8")

            assert nonai_job.load_job(path) is None

    def test_an_empty_record_means_no_job(self):
        with workspace_temp_dir() as root:
            path = root / "job.json"
            path.write_text("{}", encoding="utf-8")

            assert nonai_job.load_job(path) is None

    def test_clearing_removes_the_file_and_tolerates_it_being_gone(self):
        with workspace_temp_dir() as root:
            path = root / "job.json"
            nonai_job.save_job(path, nonai_job.Job({"pid": 1}))

            nonai_job.clear_job(path)
            nonai_job.clear_job(path)

            assert not path.exists()


def _started(**given) -> nonai_job.Job:
    fields = {"pid": 4242, "source": "C:/lib/0 unsorted/scene one.mp4",
              "tmp": "C:/lib/3 done/processed/scene one.partial.ab12.mp4",
              "out": "C:/lib/3 done/processed/scene one_apo8_iris2.mp4",
              "expected_duration": 200.0, "started_at": 1_000.0,
              "provenance": {"app": "evolver"}}
    return nonai_job.Job.started(**{**fields, **given})


class TestAJobsFields(unittest.TestCase):
    def test_a_started_job_names_its_files_as_paths(self):
        job = _started()

        assert (job.pid, job.source, job.tmp, job.out) == (
            4242, Path("C:/lib/0 unsorted/scene one.mp4"),
            Path("C:/lib/3 done/processed/scene one.partial.ab12.mp4"),
            Path("C:/lib/3 done/processed/scene one_apo8_iris2.mp4"))
        assert (job.expected_duration, job.provenance) == (200.0, {"app": "evolver"})

    def test_a_started_job_writes_the_keys_in_the_order_it_always_has(self):
        assert list(_started().fields()) == ["pid", "source", "tmp", "out", "expected_duration",
                                             "started_at", "provenance"]

    def test_one_started_on_request_is_marked_so_after_the_others(self):
        job = _started(on_request=True)

        assert list(job.fields())[-1] == "on_request"
        assert job.on_request

    def test_an_adopted_job_also_writes_that_it_is_not_suspended(self):
        job = nonai_job.Job.adopted(pid=31337, source=Path("C:/lib/a.mp4"),
                                    tmp=Path("C:/lib/a.partial.ab12.mp4"),
                                    out=Path("C:/lib/a_apo8_iris2.mp4"), expected_duration=0.0,
                                    started_at=1_000.0, provenance={"app": "evolver"})

        assert list(job.fields()) == ["pid", "source", "tmp", "out", "expected_duration",
                                      "started_at", "suspended", "suspended_at",
                                      "suspended_seconds", "provenance"]
        assert not job.suspended

    def test_a_record_missing_a_field_reads_as_that_fields_nothing(self):
        job = nonai_job.Job({})

        assert (job.pid, job.source, job.tmp, job.out) == (0, Path(), Path(), Path())
        assert (job.expected_duration, job.provenance, job.suspended, job.on_request) == (
            0.0, None, False, False)


class TestWhetherAJobIsRunning(unittest.TestCase):
    def test_a_job_whose_process_is_alive_is_running(self):
        with process_alive(return_value=True) as alive:
            assert _started().is_running()

        alive.assert_called_once_with(4242)

    def test_a_job_whose_process_has_ended_is_not(self):
        with process_alive(return_value=False):
            assert not _started().is_running()

    def test_a_job_with_no_process_is_not_and_asks_nothing(self):
        with process_alive(return_value=True) as alive:
            assert not nonai_job.Job({"pid": None}).is_running()

        alive.assert_not_called()


class TestAJobsTime(unittest.TestCase):
    def test_a_plain_run_is_the_time_since_it_started(self):
        assert nonai_job.Job({"started_at": 1_000.0}).active_runtime(now=4600.0) == 3600.0

    def test_time_already_banked_as_suspended_is_not_charged(self):
        job = nonai_job.Job({"started_at": 1_000.0, "suspended_seconds": 600.0})

        assert job.active_runtime(now=4600.0) == 3000.0

    def test_a_freeze_still_in_progress_is_not_charged_either(self):
        job = nonai_job.Job({"started_at": 1_000.0, "suspended": True, "suspended_at": 2_000.0})

        assert job.active_runtime(now=4600.0) == 1000.0

    def test_a_banked_freeze_and_a_live_one_both_count(self):
        job = nonai_job.Job({"started_at": 1_000.0, "suspended_seconds": 600.0,
                             "suspended": True, "suspended_at": 3_000.0})

        assert job.active_runtime(now=4600.0) == 1400.0

    def test_a_record_with_no_start_time_reads_as_having_just_started(self):
        assert nonai_job.Job({}).active_runtime(now=4600.0) == 0.0

    def test_suspending_marks_the_moment_and_resuming_banks_the_pause(self):
        job = _started()

        job.suspend(now=2_000.0)
        suspended = job.fields()
        job.resume(now=2_600.0)

        assert (suspended["suspended"], suspended["suspended_at"]) == (True, 2_000.0)
        assert {key: job.fields()[key] for key in ("suspended", "suspended_at",
                                                  "suspended_seconds")} == {
            "suspended": False, "suspended_at": 0.0, "suspended_seconds": 600.0}
        assert job.active_runtime(now=4_600.0) == 3_000.0

    def test_a_resume_with_no_moment_of_suspending_banks_nothing(self):
        job = nonai_job.Job({"started_at": 1_000.0, "suspended": True})

        job.resume(now=2_600.0)

        assert job.fields()["suspended_seconds"] == 0.0


class TestTheAskForAJob(unittest.TestCase):
    def test_a_job_taken_over_is_marked_asked_for(self):
        job = _started()

        job.ask_for()

        assert job.on_request
        assert job.fields()["on_request"] is True

    def test_withdrawing_the_ask_takes_the_mark_off_and_says_there_was_one(self):
        job = _started(on_request=True)

        assert job.withdraw_the_ask()
        assert not job.on_request
        assert "on_request" not in job.fields()

    def test_withdrawing_from_a_job_never_asked_for_changes_nothing(self):
        job = _started()

        assert not job.withdraw_the_ask()
        assert list(job.fields()) == list(_started().fields())


class TestAttempts(unittest.TestCase):
    def test_a_key_with_no_record_has_no_attempts(self):
        with workspace_temp_dir() as root:
            assert nonai_job.attempts_of(root / "a.json", "lagoon/a.mp4") == 0

    def test_bumping_counts_per_key(self):
        with workspace_temp_dir() as root:
            path = root / "state" / "attempts.json"

            nonai_job.bump_attempts(path, "lagoon/a.mp4")
            nonai_job.bump_attempts(path, "lagoon/a.mp4")
            nonai_job.bump_attempts(path, "other/b.mp4")

            assert nonai_job.attempts_of(path, "lagoon/a.mp4") == 2
            assert nonai_job.attempts_of(path, "other/b.mp4") == 1

    def test_clearing_one_key_leaves_the_others(self):
        with workspace_temp_dir() as root:
            path = root / "attempts.json"
            nonai_job.bump_attempts(path, "lagoon/a.mp4")
            nonai_job.bump_attempts(path, "other/b.mp4")

            nonai_job.clear_attempts(path, "lagoon/a.mp4")

            assert nonai_job.attempts_of(path, "lagoon/a.mp4") == 0
            assert nonai_job.attempts_of(path, "other/b.mp4") == 1

    def test_clearing_a_key_that_was_never_counted_writes_nothing(self):
        with workspace_temp_dir() as root:
            path = root / "attempts.json"

            nonai_job.clear_attempts(path, "lagoon/a.mp4")

            assert not path.exists()

    def test_an_unreadable_attempts_file_counts_as_empty(self):
        with workspace_temp_dir() as root:
            path = root / "attempts.json"
            path.write_text("not json", encoding="utf-8")

            assert nonai_job.attempts_of(path, "lagoon/a.mp4") == 0


class TestCooldown(unittest.TestCase):
    def test_no_stamp_means_the_epoch(self):
        with workspace_temp_dir() as root:
            assert nonai_job.last_encode_ended_at(root / "cooldown.json") == 0.0

    def test_a_stamp_reads_back_as_the_moment_it_was_written(self):
        with workspace_temp_dir() as root:
            path = root / "state" / "cooldown.json"
            before = time.time()

            nonai_job.stamp_encode_ended(path)

            stamped = nonai_job.last_encode_ended_at(path)
            assert stamped >= before
            assert stamped <= time.time()
            assert set(json.loads(path.read_text(encoding="utf-8"))) == {"ended_at"}

    def test_a_stamp_that_is_not_a_number_reads_as_the_epoch(self):
        with workspace_temp_dir() as root:
            path = root / "cooldown.json"
            path.write_text('{"ended_at": "yesterday"}', encoding="utf-8")

            assert nonai_job.last_encode_ended_at(path) == 0.0

    def test_a_cooldown_file_holding_something_else_reads_as_the_epoch(self):
        with workspace_temp_dir() as root:
            path = root / "cooldown.json"
            path.write_text('"nope"', encoding="utf-8")

            assert nonai_job.last_encode_ended_at(path) == 0.0


class TestRequest(unittest.TestCase):
    def test_a_saved_request_reads_back_naming_its_video(self):
        with workspace_temp_dir() as root:
            path = root / "state" / "request.json"

            nonai_job.save_request(path, nonai_job.Request("lagoon/0 unsorted/scene one.mp4"))

            assert nonai_job.load_request(path) == nonai_job.Request("lagoon/0 unsorted/scene one.mp4")

    def test_nothing_was_asked_for_when_the_file_is_absent_or_unreadable(self):
        for written in (None, '{"video": "lagoon/0 un', "[1, 2]", '{"held_back": "low_ram"}'):
            with self.subTest(written=written), workspace_temp_dir() as root:
                path = root / "request.json"
                if written is not None:
                    path.write_text(written, encoding="utf-8")

                assert nonai_job.load_request(path) is None

    def test_a_request_the_computer_held_back_keeps_the_reason(self):
        with workspace_temp_dir() as root:
            path = root / "request.json"
            held = nonai_job.Request("lagoon/0 unsorted/scene one.mp4", held_back="low_ram")

            nonai_job.save_request(path, held)

            assert nonai_job.load_request(path) == held

    def test_clearing_removes_the_request_and_tolerates_it_being_gone(self):
        with workspace_temp_dir() as root:
            path = root / "request.json"
            nonai_job.save_request(path, nonai_job.Request("lagoon/0 unsorted/a.mp4"))

            nonai_job.clear_request(path)
            nonai_job.clear_request(path)

            assert nonai_job.load_request(path) is None
            assert not path.exists()


if __name__ == "__main__":
    unittest.main()
