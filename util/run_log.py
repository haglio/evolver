from __future__ import annotations

from datetime import datetime
from pathlib import Path

MAX_BYTES = 4 << 20

TRUNCATION_NOTE = "... (this excerpt hit its size limit; the rest is in the log file)"


def run_id(started_at: datetime) -> str:
    return started_at.strftime("%Y-%m-%dT%H-%M-%S")


def banner(run_id: str) -> str:
    return f"=== Evolver run {run_id} ==="


def size(log_path: Path) -> int | None:
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
    # logging writes CRLF in text mode on Windows; a text widget draws a blank line between them.
    text = (first + rest).decode("utf-8", "replace").replace("\r\n", "\n")
    text = text.rstrip("\n")
    if end - start > max_bytes:
        text += "\n" + TRUNCATION_NOTE
    return text
