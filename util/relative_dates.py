from __future__ import annotations

import calendar
import datetime
import re

_RELATIVE_DATE_RE = re.compile(r"^(\d+)(mo|[mhdw])\s+ago$", re.IGNORECASE)


def today() -> datetime.date:
    return datetime.datetime.now().astimezone().date()


def as_iso_date(value: str) -> str:
    match = _RELATIVE_DATE_RE.match(value.strip())
    if not match:
        return value
    amount = int(match.group(1))
    unit = match.group(2).lower()
    now = today()
    if unit in {"m", "h"}:
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
        day = min(now.day, calendar.monthrange(year, month)[1])
        return datetime.date(year, month, day).isoformat()
    return value

