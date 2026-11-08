from __future__ import annotations

import subprocess
from pathlib import Path

# The scraped pages build themselves in script, their fetched HTML an empty shell: Chrome runs it.
_BROWSER_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)

# Chrome virtual time, not wall clock: the browser fast-forwards its timers.
_VIRTUAL_TIME_BUDGET_MS = 10000


def find_browser_executable() -> Path | None:
    for candidate in _BROWSER_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def fetch_dom(url: str, browser: Path, *, profile_dir: Path) -> str:
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
