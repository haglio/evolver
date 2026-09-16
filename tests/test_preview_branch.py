from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import preview_branch


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
        window = preview_branch.PreviewWindow()
        window.show()

        self.assertTrue(window.close())
        self.assertFalse(window.isVisible())


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
