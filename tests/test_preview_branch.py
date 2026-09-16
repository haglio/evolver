from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import config
import preview_branch
from tasks import nonai_queue
from tests.temp_helpers import override_config, workspace_temp_dir
from util import nonai_job


class TestSignInDeferral(unittest.TestCase):
    def test_an_expired_topaz_sign_in_is_the_reason_a_start_would_wait(self):
        with patch("util.processes.count_running", return_value=0), \
             patch("util.topaz.sign_in_expired", return_value=True):
            self.assertEqual(preview_branch.sign_in_deferral(), "topaz_sign_in_expired")

    def test_no_sign_in_check_runs_beside_a_topaz_encode_already_running(self):
        with patch("util.processes.count_running", return_value=1), \
             patch("util.topaz.sign_in_expired", return_value=True) as sign_in_expired:
            self.assertEqual(preview_branch.sign_in_deferral(), "")

        sign_in_expired.assert_not_called()


class TestPreviewWindow(unittest.TestCase):
    def test_closing_the_preview_window_ends_the_preview_rather_than_hiding_it(self):
        window = preview_branch.PreviewWindow(preview_branch.preview_files(Path("state")))
        window.show()

        self.assertTrue(window.close())
        self.assertFalse(window.isVisible())


class TestTheQueueTheWindowShows(unittest.TestCase):
    """The preview opens the real queue window on the real library, so every
    file it writes has to be a copy -- and the encode it is watching belongs to
    the app that is running, which this must not touch."""

    def test_every_record_the_window_writes_is_the_previews_own_copy(self):
        files = preview_branch.preview_files(Path("state"))

        written = (files.job, files.attempts, files.cooldown, files.request,
                   files.pin_manifest, files.skip_manifest)

        self.assertTrue(all(path.parent == Path("state") for path in written), written)
        self.assertEqual(files.watch_stats, config.FUN_TIME_WATCH_STATS_FILE)

    def test_the_copies_are_filled_from_the_live_records(self):
        with workspace_temp_dir() as root:
            primary, state = root / "primary", root / "state"
            primary.mkdir()
            (primary / config.NONAI_PRIORITY_MANIFEST.name).write_text(
                "larkin/0 unsorted/a.mp4\n", encoding="utf-8")
            live_job = root / "live_job.json"
            live_job.write_text('{"pid": 4242}', encoding="utf-8")
            files = preview_branch.preview_files(state)

            with override_config(NONAI_JOB_STATE_FILE=live_job):
                preview_branch.copy_the_live_records_in(primary, files)

            self.assertEqual(files.pin_manifest.read_text(encoding="utf-8"),
                             "larkin/0 unsorted/a.mp4\n")
            self.assertEqual(nonai_job.load_job(files.job), {"pid": 4242})

    def test_a_copy_of_a_record_the_live_app_no_longer_has_is_cleared(self):
        """A request answered since the last preview would otherwise be shown
        as still waiting, every launch."""
        with workspace_temp_dir() as root:
            primary, state = root / "primary", root / "state"
            primary.mkdir()
            files = preview_branch.preview_files(state)
            state.mkdir()
            files.request.write_text('{"video": "larkin/0 unsorted/a.mp4"}', encoding="utf-8")

            with override_config(NONAI_REQUEST_FILE=root / "no_request.json"):
                preview_branch.copy_the_live_records_in(primary, files)

            self.assertIsNone(nonai_job.load_request(files.request))

    def test_asking_for_a_video_here_stops_the_live_encode_on_paper_only(self):
        with workspace_temp_dir() as root:
            state = root / "state"
            files = preview_branch.preview_files(state)
            state.mkdir()
            nonai_job.save_job(files.job, {"pid": 4242, "source": str(
                config.NON_AI_DIR / "larkin" / "0 unsorted" / "busy.mp4")})

            with patch("util.processes.terminate") as terminate, \
                 patch("util.processes.is_running", return_value=True), \
                 patch("util.processes.resume") as resume:
                preview_branch.PreviewWindow(files)._ask_for("larkin/0 unsorted/a.mp4")

            terminate.assert_not_called()
            resume.assert_not_called()
            self.assertIsNone(nonai_job.load_job(files.job))
            self.assertEqual(nonai_job.load_request(files.request).video,
                             "larkin/0 unsorted/a.mp4")
            self.assertEqual(nonai_queue.manifest_entries(files.pin_manifest),
                             ["larkin/0 unsorted/a.mp4", "larkin/0 unsorted/busy.mp4"])


if __name__ == "__main__":
    unittest.main()


class TestNonAiTitlesReport(unittest.TestCase):
    def test_it_counts_what_the_stage_would_name_without_writing_a_sidecar(self):
        """The preview reads the real library, so the row has to be reachable
        without doing the stage's work -- and the number worth judging is how
        much of the library the clip records reach."""
        payloads = {
            "scene.mp4": {"version": {"group": "scene"}},
            "clip.mp4": {"version": {"group": "clip"},
                         "clip": {"performer": "Jane Doe", "source": "Alpha Study 3",
                                  "full_video": "scene.mp4"}},
            "lone.mp4": {"version": {"group": "lone"}},
        }
        with patch("preview_branch._library_payloads", return_value=payloads),              patch("util.sidecar.update") as wrote:
            record = preview_branch.nonai_titles_report(Path("preview"), Path("primary"))

        self.assertEqual(record.name, "title_non_ai")
        self.assertEqual((record.result.titled, record.result.videos), (2, 3))
        self.assertEqual(record.result.written, 0)
        wrote.assert_not_called()
