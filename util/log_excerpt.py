"""The stretch of the log written between two moments.

Evolver's log is one appending file that nothing rotates -- months of runs,
hundreds of megabytes -- so the lines a single run wrote cannot be found by
reading it. Every line carries the second it was written at and the file is in
that order, so the start is found by bisecting the file's own bytes and only
that one stretch is ever read.

The stamps are what ``logging`` wrote: the machine's LOCAL wall clock, to the
second. Callers hold aware datetimes (a run record's are UTC), and that
conversion happens here, once. The one place the ordering this leans on breaks
is the repeated hour of a fall-back DST change, where a wall clock genuinely
does go backwards; a run inside that hour can land an hour of the log away.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

# evolver.setup_logging's "[%(asctime)s] " prefix, at logging's default
# datefmt. Nineteen characters between the brackets, so reading a stamp is a
# slice and a strptime rather than a regex -- it runs once per line.
_STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
_STAMP_END = 20  # index of the "]" that closes the stamp

# The bisect's step. Large enough that the search is a couple of dozen seeks on
# a file of any size, small enough that the linear read it hands over to starts
# at most two of these before the run.
_BLOCK = 1 << 16

# How far past a block's start to keep looking for a line that carries a stamp.
# Only a traceback has none -- logging writes one record, and its continuation
# lines are unprefixed -- and a megabyte is longer than any of them.
_STAMP_SEARCH_BYTES = 1 << 20

# A stamp is the second the line was written IN, truncated: a line logged at
# 20:39:59.8 reads 20:39:59, which is before the moment a run that began at
# 20:39:59.9 says it began. Comparing the two directly would drop that line,
# and it is the one naming the stage that opened the run. Reading from a
# little earlier cannot, and costs at most a line or two of the quiet between
# runs.
_LEAD = timedelta(seconds=2)

# A run's stretch is a few kilobytes. This is the ceiling for one that went
# wrong -- a stage looping, or a span so wide that the excerpt is really the
# log.
MAX_BYTES = 4 << 20

TRUNCATION_NOTE = "... (this excerpt hit its size limit; the rest is in the log file)"


def excerpt(
    log_path: Path,
    start: datetime,
    end: datetime,
    *,
    max_bytes: int = MAX_BYTES,
) -> str:
    """Every log line stamped between *start* and *end*, both aware datetimes.

    Empty when the log has nothing in that span: it does not reach back that
    far, it has been deleted since, or nothing was written while the run ran.
    """
    if not log_path.is_file():
        return ""
    first = _local(start) - _LEAD
    last = _local(end)
    size = log_path.stat().st_size
    with log_path.open("rb") as handle:
        return _read_span(handle, _block_before(handle, size, first),
                          size, first, last, max_bytes)


def _read_span(handle, offset, size, first, last, max_bytes) -> str:
    """Read forward from *offset*, keeping the lines between *first* and *last*.

    An unstamped line is a traceback's continuation: it belongs to whichever
    record it trails, so it is kept once the span has been entered and dropped
    while the read is still catching up to it.
    """
    handle.seek(offset)
    if offset:
        handle.readline()  # the partial line an offset lands inside
    kept: list[str] = []
    total = 0
    entered = False
    while handle.tell() < size:
        raw = handle.readline()
        line = raw.decode("utf-8", "replace")
        stamp = _stamp(line)
        if stamp is not None:
            if stamp < first:
                continue
            if stamp > last:
                break
            entered = True
        elif not entered:
            continue
        total += len(raw)
        if total > max_bytes:
            kept.append(TRUNCATION_NOTE)
            break
        kept.append(line)
    return "".join(kept).rstrip("\n")


def _block_before(handle, size, target) -> int:
    """A block boundary at or before the first line stamped *target* or later.

    Bisects over block NUMBERS rather than over byte offsets: an offset lands
    mid-line, and a search whose step is "the next line" has to reason about a
    step that overshoots the bracket it is narrowing. Blocks are fixed, so this
    is an ordinary integer bisect. It then backs up one, because the caller
    reads forward from here: a block early costs 64 KiB of scanning, and a
    block late would cost the run its opening lines.
    """
    lo, hi = 0, size // _BLOCK
    while lo < hi:
        mid = (lo + hi) // 2
        stamp = _first_stamp(handle, mid * _BLOCK, size)
        if stamp is None or stamp >= target:
            hi = mid
        else:
            lo = mid + 1
    return max(lo - 1, 0) * _BLOCK


def _first_stamp(handle, offset, size) -> datetime | None:
    """The stamp of the first whole line at or after *offset*."""
    handle.seek(offset)
    if offset:
        handle.readline()
    limit = min(size, offset + _STAMP_SEARCH_BYTES)
    while handle.tell() < limit:
        stamp = _stamp(handle.readline().decode("utf-8", "replace"))
        if stamp is not None:
            return stamp
    return None


def _stamp(line: str) -> datetime | None:
    """When *line* was logged, or None if it carries no stamp of its own."""
    if len(line) <= _STAMP_END or line[0] != "[" or line[_STAMP_END] != "]":
        return None
    try:
        return datetime.strptime(line[1:_STAMP_END], _STAMP_FORMAT)
    except ValueError:
        return None


def _local(moment: datetime) -> datetime:
    """*moment* on the naive wall clock the log's stamps are written in."""
    return moment.astimezone().replace(tzinfo=None)
