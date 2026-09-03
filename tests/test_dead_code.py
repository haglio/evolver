"""Dead-code detection — fails if vulture finds unreferenced code."""

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from tests.temp_helpers import workspace_temp_dir

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _source_files(root: Path) -> list[str]:
    """Every product ``.py`` file under *root*, as root-relative paths.

    The tests are left out: they name everything the product exports, so
    scanning them would mark all of it used.  ``tools`` is left out for the
    opposite reason — it is developer tooling the suite drives (the sanitize
    guard), never reached from the app, so vulture would call all of it dead.
    So are the trees that hold no product code of this checkout's own — hidden
    ones (``.venv``, ``.git``, and ``.claude``, which in the primary checkout
    holds whole worktree copies) and generated ones (``__pycache__``).
    """
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in ("tests", "tools") and not name.startswith((".", "__"))
        ]
        found += [
            Path(dirpath, name).relative_to(root).as_posix()
            for name in filenames
            if name.endswith(".py")
        ]
    return sorted(found)


def _run_vulture(root: Path) -> subprocess.CompletedProcess:
    """Scan *root*'s sources, naming each file rather than excluding the rest.

    Vulture matches ``--exclude`` patterns against *absolute* paths, so a
    checkout whose own path contains an excluded word had every one of its files
    excluded — and agents work in worktrees under ``<repo>/.claude/``.  Handing
    vulture the files outright leaves no pattern left to misfire, and the assert
    keeps a scan that reached nothing from reading as a clean bill of health.
    """
    sources = _source_files(root)
    assert sources, f"no Python sources found under {root} — nothing would be checked"
    return subprocess.run(
        [sys.executable, "-m", "vulture", *sources],
        capture_output=True,
        text=True,
        cwd=str(root),
    )


WHITELIST = PROJECT_ROOT / "vulture_whitelist.py"


def _whitelisted_names() -> list[str]:
    """The names ``vulture_whitelist.py`` claims are framework-called."""
    return re.findall(r"^_\.(\w+)", WHITELIST.read_text(encoding="utf-8"), re.MULTILINE)


def _names_vulture_reports_unwhitelisted() -> set[str]:
    """What the guard would report with the whitelist taken out of the scan."""
    sources = [f for f in _source_files(PROJECT_ROOT) if f != WHITELIST.name]
    result = subprocess.run(
        [sys.executable, "-m", "vulture", *sources],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )
    return set(re.findall(r"unused \w+ '(\w+)'", result.stdout))


class TestDeadCode(unittest.TestCase):
    def test_no_dead_code(self):
        result = _run_vulture(PROJECT_ROOT)
        self.assertEqual(result.returncode, 0, f"Vulture found dead code:\n{result.stdout}")

    def test_every_whitelist_entry_suppresses_something(self):
        """An entry that suppresses nothing is worse than no entry at all.

        The file's own docstring says to add only names vulture would report,
        and an inert line still tells the next reader that an ordinary method
        is reached by framework magic. Measured, not asserted from memory: the
        guard is re-run with the whitelist out of the scan, and every entry
        whose name that run does not report is dead weight.
        """
        reported = _names_vulture_reports_unwhitelisted()
        inert = sorted(set(_whitelisted_names()) - reported)
        self.assertEqual(inert, [], f"whitelist entries suppressing nothing: {inert}")

    def test_a_checkout_under_dot_claude_is_still_scanned(self):
        """Agents work in worktrees at ``<repo>/.claude/worktrees/<name>/``."""
        with workspace_temp_dir() as temp:
            root = temp / ".claude" / "worktrees" / "some_agent"
            (root / "pkg").mkdir(parents=True)
            (root / "pkg" / "mod.py").write_text("UNREAD = 'nothing reads this'\n")

            result = _run_vulture(root)

        self.assertIn("unused variable 'UNREAD'", result.stdout)


if __name__ == "__main__":
    unittest.main()
