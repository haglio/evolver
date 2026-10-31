"""Driving an installed browser headless to get a page's rendered DOM."""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

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
                found = headless_browser.find_browser_executable()

        assert found == second


    def test_no_browser_installed_is_no_answer_rather_than_an_error(self):
        """The stage degrades to "scraping unavailable this run" on a None; an
        exception here would take the whole pipeline tick down."""
        with workspace_temp_dir() as root:
            with patch.object(headless_browser, "_BROWSER_CANDIDATES",
                              (root / "chrome.exe",)):
                assert headless_browser.find_browser_executable() is None


class TestFetchDom(unittest.TestCase):
    def test_the_page_the_browser_dumped_is_what_the_caller_gets(self):
        with workspace_temp_dir() as root:
            with patch("subprocess.run", return_value=_completed(stdout="<p>hi</p>")):
                dom = headless_browser.fetch_dom(
                    "https://example.invalid/a", Path("chrome.exe"),
                    profile_dir=root / "profile")

            assert dom == "<p>hi</p>"

    def test_the_profile_directory_it_is_given_is_the_one_the_browser_gets(self):
        """The browser writes into it, so a default under the checkout would be
        a running app leaving scratch state in a git working tree."""
        with workspace_temp_dir() as root:
            profile = root / "somewhere" / "profile"

            with patch("subprocess.run", return_value=_completed()) as run:
                headless_browser.fetch_dom("https://example.invalid/a",
                                           Path("chrome.exe"), profile_dir=profile)

            assert profile.is_dir()
            assert f"--user-data-dir={profile}" in run.call_args.args[0]

    def test_the_browser_it_is_given_is_the_one_launched(self):
        with workspace_temp_dir() as root:
            with patch("subprocess.run", return_value=_completed()) as run:
                headless_browser.fetch_dom("https://example.invalid/a",
                                           Path("/opt/msedge"), profile_dir=root)

            argv = run.call_args.args[0]
            assert argv[0] == str(Path("/opt/msedge"))
            assert argv[-1] == "https://example.invalid/a"

    def test_a_nonzero_exit_names_the_url_and_what_the_browser_said(self):
        with workspace_temp_dir() as root:
            with patch("subprocess.run",
                       return_value=_completed(returncode=1, stderr="no display")), \
                 pytest.raises(RuntimeError) as caught:
                headless_browser.fetch_dom("https://example.invalid/a",
                                           Path("chrome.exe"), profile_dir=root)

            assert "https://example.invalid/a" in str(caught.value)
            assert "no display" in str(caught.value)

    def test_a_silent_nonzero_exit_still_says_what_the_code_was(self):
        with workspace_temp_dir() as root:
            with patch("subprocess.run", return_value=_completed(returncode=3)), \
                 pytest.raises(RuntimeError) as caught:
                headless_browser.fetch_dom("https://example.invalid/a",
                                           Path("chrome.exe"), profile_dir=root)

            assert "exit 3" in str(caught.value)


if __name__ == "__main__":
    unittest.main()
