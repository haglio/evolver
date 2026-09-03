"""Turning "2d ago" into a date, for pages that only say how long ago.

A site that shows a creation time as "3mo ago" is saying something about the
day it is read, so the answer has to be computed against today rather than
parsed out of the string. Anything that is not one of these phrasings comes
back exactly as it went in — an absolute date already on the page is the
common case and must not be rewritten.
"""

from __future__ import annotations

import datetime
import re

# "5m ago", "5h ago", "2d ago", "2w ago", "3mo ago" -- mo before the single
# letters, or "3mo" would read as three minutes followed by a stray "o".
_RELATIVE_DATE_RE = re.compile(r"^(\d+)(mo|[mhdw])\s+ago$", re.IGNORECASE)


def today() -> datetime.date:
    """The day to count back from — a function so a test can fix it."""
    return datetime.date.today()


def as_iso_date(value: str) -> str:
    """*value* as ``YYYY-MM-DD`` when it says how long ago, else *value* itself.

    Minutes and hours ago are still today: the pages this reads give no clock
    time, so an "8h ago" that crossed midnight is not recoverable and today is
    the closest true answer. Months count back by calendar month and clamp the
    day, so "1mo ago" on the 31st lands on the last day of the shorter month
    rather than overflowing into this one.
    """
    match = _RELATIVE_DATE_RE.match(value.strip())
    if not match:
        return value
    amount = int(match.group(1))
    unit = match.group(2).lower()
    now = today()
    if unit == "m" or unit == "h":
        return now.isoformat()
    if unit == "d":
        return (now - datetime.timedelta(days=amount)).isoformat()
    if unit == "w":
        return (now - datetime.timedelta(weeks=amount)).isoformat()
    if unit == "mo":
        month = now.month - amount
        year = now.year
        while month < 1:
            month += 12
            year -= 1
        day = min(now.day, _days_in_month(year, month))
        return datetime.date(year, month, day).isoformat()
    return value


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)).day
