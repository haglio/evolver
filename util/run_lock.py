"""One pipeline run on the machine at a time, whichever Evolver starts it.

Only one tray Evolver is ever up (``gui/single_instance.py``), but a
command-line run can start while the tray's runs go on.  Each would sort the
same inbox and purge the same piles; the upscale stages check for a live Topaz
process before starting one, but between two sorts nothing stood.  The turn is a file in the machine-local
state folder, created exclusively and holding the runner's process number.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from util import processes

# Far past the eleven minutes the tray's watchdog allows a run: a turn this old
# was left by a run that died, whatever process now has its number.
LONGEST_RUN_SECONDS = 60 * 60


class Busy(RuntimeError):
    """Another Evolver is running the pipeline, so this run did not start."""


@contextmanager
def held(lock: Path) -> Iterator[None]:
    """Hold the pipeline's turn for the length of the ``with`` block."""
    lock.parent.mkdir(parents=True, exist_ok=True)
    if not _claim(lock):
        if _still_held(lock):
            raise Busy(f"another Evolver (process {_holder(lock)}) is running the pipeline")
        lock.unlink(missing_ok=True)
        if not _claim(lock):
            raise Busy("another Evolver took the pipeline's turn at the same moment")
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _claim(lock: Path) -> bool:
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(handle, str(os.getpid()).encode("ascii"))
    finally:
        os.close(handle)
    return True


def _holder(lock: Path) -> int:
    try:
        return int(lock.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


def _still_held(lock: Path) -> bool:
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return False
    holder = _holder(lock)
    return bool(holder) and age < LONGEST_RUN_SECONDS and processes.is_running(holder)
