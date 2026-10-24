"""Start the work Origenerator leaves for while it is closed, by asking it to.

Origenerator alone knows what that work is and whether it is closed, so this
stage only runs the command it publishes beside the rest of what Evolver reads
of it, and passes on what the command answers: what it did, and whether a fix's
training now holds the graphics card, which the upscale stays off meanwhile.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app_support.subprocess_utils import hidden_subprocess_kwargs

import config
from util import origenerator_gallery

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 8 * 60


@dataclass
class DowntimeResult:
    did: str = ""
    holds_the_graphics_card: bool = False
    failed: bool = False


def run(checkout: Path | None = None, *, runner=subprocess.run) -> DowntimeResult:
    checkout = config.ORIGENERATOR_PROJECT_DIR if checkout is None else checkout
    command = origenerator_gallery.downtime_command(checkout)
    if command is None:
        return DowntimeResult(did="nothing: Origenerator names no work for while it is closed")
    interpreter, *arguments = command
    try:
        answered = runner([str(checkout / interpreter), *arguments], cwd=str(checkout),
                          capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
                          **hidden_subprocess_kwargs())
        said = json.loads(answered.stdout.strip().splitlines()[-1])
        result = DowntimeResult(did=str(said["did"]),
                                holds_the_graphics_card=said["holds_the_graphics_card"] is True)
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, IndexError,
            TypeError) as e:
        log.warning("Origenerator's work for while it is closed could not be asked for: %s", e)
        return DowntimeResult(failed=True)
    log.info("Origenerator, while closed: %s%s", result.did,
             "; a fix's training holds the graphics card" if result.holds_the_graphics_card else "")
    return result
