from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

import config
from util import lanes
from util.origenerator_gallery import PUBLISHED

log = logging.getLogger(__name__)

DOWNTIME = "downtime_command"
GALLERY_ENTRIES = "outside_video_entries_command"
_GIVEN_SECONDS = {DOWNTIME: 8 * 60, GALLERY_ENTRIES: 2 * 60}
_UNANSWERED = (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError, TypeError)


@dataclass
class DowntimeResult:
    did: str = ""
    holds_the_graphics_card: bool = False
    failed: bool = False


def published_command(checkout: Path, name: str) -> tuple[str, ...] | None:
    try:
        published = json.loads((checkout / PUBLISHED).read_text(encoding="utf-8"))
        command = tuple(str(part) for part in published[name])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return command or None


def _answer(name: str, checkout: Path | None, runner) -> dict | None:
    checkout = config.ORIGENERATOR_PROJECT_DIR if checkout is None else checkout
    command = published_command(checkout, name)
    if command is None:
        return None
    interpreter, *arguments = command
    answered = runner([str(checkout / interpreter), *arguments], cwd=str(checkout),
                      capture_output=True, text=True, timeout=_GIVEN_SECONDS[name],
                      **hidden_subprocess_kwargs())
    return json.loads(answered.stdout.strip().splitlines()[-1])


def run_downtime(checkout: Path | None = None, *, runner=subprocess.run) -> DowntimeResult:
    try:
        said = _answer(DOWNTIME, checkout, runner)
        if said is None:
            return DowntimeResult(did="nothing: Origenerator names no work for while it is closed")
        result = DowntimeResult(did=str(said["did"]),
                                holds_the_graphics_card=said["holds_the_graphics_card"] is True)
    except _UNANSWERED as e:
        log.warning("Origenerator's work for while it is closed could not be asked for: %s", e)
        return DowntimeResult(failed=True)
    log.info("Origenerator, while closed: %s%s", result.did,
             "; a fix's training holds the graphics card" if result.holds_the_graphics_card else "")
    return result


def write_gallery_entries(checkout: Path | None = None, *, runner=subprocess.run) -> bool:
    try:
        said = _answer(GALLERY_ENTRIES, checkout, runner)
        brought_in = 0 if said is None else int(said["brought_in"])
    except _UNANSWERED as e:
        log.warning("Origenerator's gallery could not be told what the library holds: %s", e)
        return False
    if brought_in:
        log.info("Origenerator's gallery took in %d video(s) other sites made", brought_in)
    return True


def write_the_gallery_entry_of_a_video_from(
        source: str, *, write: Callable[[], object] = write_gallery_entries) -> None:
    if not lanes.sent_by_origenerator(source):
        write()
