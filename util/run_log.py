"""Where a run's own lines are in the log, marked as the run writes them.

Evolver's log is one appending file that nothing rotates -- months of runs,
hundreds of megabytes -- so the lines a single run wrote have to be pointed at
rather than searched for. A run opens with a banner naming itself and records
the byte offsets either side of its own output, so reading it back is a seek
and a read of exactly those bytes. The banner is what makes the offsets safe:
they are checked against it before a byte is shown, so a log that has been
replaced or trimmed under them shows nothing rather than somebody else's run.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

# A run's stretch is a few kilobytes. This is the ceiling for one that went
# wrong -- a stage looping over a library that grew, or a watchdogged run that
# spent eleven minutes saying so.
MAX_BYTES = 4 << 20

TRUNCATION_NOTE = "... (this excerpt hit its size limit; the rest is in the log file)"


def run_id(started_at: datetime) -> str:
    """The name a run is filed and logged under: when it began, to the second.

    One definition, because two things have to agree on it -- the banner the
    pipeline writes and the record the GUI reads back -- and a run whose record
    and banner disagreed would simply never be found.
    """
    return started_at.strftime("%Y-%m-%dT%H-%M-%S")


def banner(run_id: str) -> str:
    """The line a run opens with, which is also how its offset is checked."""
    return f"=== Evolver run {run_id} ==="


def size(log_path: Path) -> int | None:
    """How many bytes the log holds right now, or None if there is no log.

    Called either side of a run to mark where its output begins and ends. None
    rather than 0 for a missing file: 0 is a real offset into a log that
    exists, and a run that could not be marked has to be told apart from one
    that starts at the top.
    """
    try:
        return log_path.stat().st_size
    except OSError:
        return None


def read_run(
    log_path: Path,
    run_id: str,
    start: int | None,
    end: int | None,
    *,
    max_bytes: int = MAX_BYTES,
) -> str | None:
    """The bytes *run_id* wrote, or None if they cannot be vouched for.

    None covers every way the mark can fail to lead anywhere: a record written
    before runs marked themselves, a log deleted or trimmed since -- and the
    case the banner exists to catch, a log replaced by a different one long
    enough that the offsets still land inside it, on somebody else's run. An
    empty string is a different answer: the mark was good and the run wrote
    nothing.
    """
    if start is None or end is None or end < start or not log_path.is_file():
        return None
    if end > log_path.stat().st_size:
        return None
    with log_path.open("rb") as handle:
        handle.seek(start)
        first = handle.readline()
        if banner(run_id) not in first.decode("utf-8", "replace"):
            return None
        rest = handle.read(max(0, min(end, start + max_bytes) - handle.tell()))
    # Normalized, not passed through: logging writes this file in text mode,
    # so on Windows every line ends CRLF, and a text widget handed those draws
    # a blank line between every line of the log.
    text = (first + rest).decode("utf-8", "replace").replace("\r\n", "\n")
    text = text.rstrip("\n")
    if end - start > max_bytes:
        text += "\n" + TRUNCATION_NOTE
    return text
