"""Dumping a page's rendered DOM by driving an installed Chrome or Edge headless.

The pages this exists for build their content in JavaScript, so fetching the
HTML gets an empty shell; the only thing on these machines that will run the
scripts and hand back what a reader would see is a browser already installed
for browsing. It is driven as a one-shot subprocess -- launch, dump, exit --
rather than kept alive, because the caller is a pipeline stage that a watchdog
kills at eleven minutes and a wedged browser must not be something it inherits.

The profile directory is the caller's to name. The browser writes into it, and
a default under the checkout is a running app leaving its scratch state in a
git working tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Where the two Chromium-family browsers install themselves on Windows, most
# likely first. Either will do: the page is dumped, not interacted with.
_BROWSER_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)

# Long enough for the pages in question to finish their fetches and render,
# short enough that a stalled one dies well inside the pipeline's own ceiling.
# Virtual time, so it is not wall-clock: the browser fast-forwards its timers.
_VIRTUAL_TIME_BUDGET_MS = 10000


def find_browser_executable() -> Path | None:
    """The first installed Chromium-family browser, or None if there is none."""
    for candidate in _BROWSER_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def fetch_dom(url: str, browser: Path, *, profile_dir: Path) -> str:
    """*url*'s rendered DOM, as the given browser sees it after its scripts run.

    Raises ``RuntimeError`` naming the URL when the browser exits non-zero --
    the caller turns that into a failure marker beside the sidecar it could not
    write, so the same page is not retried every run.
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            str(browser),
            "--headless=new",
            "--disable-gpu",
            "--disable-breakpad",
            "--disable-crash-reporter",
            "--no-first-run",
            f"--user-data-dir={profile_dir}",
            f"--virtual-time-budget={_VIRTUAL_TIME_BUDGET_MS}",
            "--dump-dom",
            url,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"Browser DOM dump failed for {url}: {stderr}")
    return proc.stdout
