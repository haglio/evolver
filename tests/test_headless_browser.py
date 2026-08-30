"""Driving an installed browser headless to get a page's rendered DOM."""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.temp_helpers import workspace_temp_dir
from util import headless_browser


def _completed(returncode=0, stdout="<html></html>", stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestFindBrowserExecutable(unittest.TestCase):
    def test_takes_the_first_candidate_that_is_installed(self):
        with workspace_temp_dir() as root:
            second = root / "msedge.exe"
            second.write_text("x", encoding="utf-8")
            candidates = (root / "chrome.exe", second, root / "other.exe")

            with patch.object(headless_browser, "_BROWSER_CANDIDATES", candidates):
                self.assertEqual(headless_browser.find_browser_executable(), second)

    def test_no_browser_installed_is_no_answer_rather_than_an_error(self):
        """The stage degrades to "scraping unavailable this run" on a None; an
        exception here would take the whole pipeline tick down."""
        with workspace_temp_dir() as root:
            with patch.object(headless_browser, "_BROWSER_CANDIDATES",
                              (root / "chrome.exe",)):
                self.assertIsNone(headless_browser.find_browser_executable())


class TestFetchDom(unittest.TestCase):
    def test_returns_what_the_browser_dumped(self):
        with workspace_temp_dir() as root:
            with patch("subprocess.run", return_value=_completed(stdout="<p>hi</p>")):
                dom = headless_browser.fetch_dom(
                    "https://example.invalid/a", Path("chrome.exe"),
                    profile_dir=root / "profile")

            self.assertEqual(dom, "<p>hi</p>")

    def test_the_profile_directory_it_is_given_is_the_one_the_browser_gets(self):
        """The browser writes into it, so a default under the checkout would be
        a running app leaving scratch state in a git working tree."""
        with workspace_temp_dir() as root:
            profile = root / "somewhere" / "profile"

            with patch("subprocess.run", return_value=_completed()) as run:
                headless_browser.fetch_dom("https://example.invalid/a",
                                           Path("chrome.exe"), profile_dir=profile)

            self.assertTrue(profile.is_dir())
            self.assertIn(f"--user-data-dir={profile}", run.call_args.args[0])

    def test_the_browser_it_is_given_is_the_one_launched(self):
        with workspace_temp_dir() as root:
            with patch("subprocess.run", return_value=_completed()) as run:
                headless_browser.fetch_dom("https://example.invalid/a",
                                           Path("/opt/msedge"), profile_dir=root)

            argv = run.call_args.args[0]
            self.assertEqual(argv[0], str(Path("/opt/msedge")))
            self.assertEqual(argv[-1], "https://example.invalid/a")

    def test_a_nonzero_exit_names_the_url_and_what_the_browser_said(self):
        with workspace_temp_dir() as root:
            with patch("subprocess.run",
                       return_value=_completed(returncode=1, stderr="no display")):
                with self.assertRaises(RuntimeError) as caught:
                    headless_browser.fetch_dom("https://example.invalid/a",
                                               Path("chrome.exe"), profile_dir=root)

            self.assertIn("https://example.invalid/a", str(caught.exception))
            self.assertIn("no display", str(caught.exception))

    def test_a_silent_nonzero_exit_still_says_what_the_code_was(self):
        with workspace_temp_dir() as root:
            with patch("subprocess.run", return_value=_completed(returncode=3)):
                with self.assertRaises(RuntimeError) as caught:
                    headless_browser.fetch_dom("https://example.invalid/a",
                                               Path("chrome.exe"), profile_dir=root)

            self.assertIn("exit 3", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
