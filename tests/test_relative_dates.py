"""Reading "how long ago" off a page as a date.

These moved out of tests/test_prompt_scrape.py with the parser. The clock is
fixed by patching the module's own ``today``, which is the reason that function
exists rather than a bare ``datetime.date.today()`` inline.
"""

import datetime
import unittest
from unittest.mock import patch

from util import relative_dates

# A Saturday, and the 28th, so counting back three months lands on a day every
# month has and counting back one from the 31st is a separate case below.
TODAY = datetime.date(2026, 3, 28)


class TestAsIsoDate(unittest.TestCase):
    def test_days_ago(self):
        with patch("util.relative_dates.today", return_value=TODAY):
            self.assertEqual(relative_dates.as_iso_date("2d ago"), "2026-03-26")

    def test_weeks_ago(self):
        with patch("util.relative_dates.today", return_value=TODAY):
            self.assertEqual(relative_dates.as_iso_date("2w ago"), "2026-03-14")

    def test_months_ago(self):
        with patch("util.relative_dates.today", return_value=TODAY):
            self.assertEqual(relative_dates.as_iso_date("3mo ago"), "2025-12-28")

    def test_months_ago_clamps_to_the_shorter_months_last_day(self):
        """Counting back from the 31st must not overflow into the month after
        the one it landed in."""
        with patch("util.relative_dates.today", return_value=datetime.date(2026, 3, 31)):
            self.assertEqual(relative_dates.as_iso_date("1mo ago"), "2026-02-28")

    def test_months_ago_across_a_december_boundary_clamps_too(self):
        """December is the one month _days_in_month answers without arithmetic,
        so it is the branch a rewrite would most easily get wrong."""
        with patch("util.relative_dates.today", return_value=datetime.date(2026, 1, 31)):
            self.assertEqual(relative_dates.as_iso_date("1mo ago"), "2025-12-31")

    def test_minutes_ago(self):
        # The 'm' unit had no case at all: collapsing the minutes branch into
        # the hours one survived the whole file (audit probe P8).
        with patch("util.relative_dates.today", return_value=TODAY):
            self.assertEqual(relative_dates.as_iso_date("5m ago"), "2026-03-28")

    def test_hours_ago(self):
        with patch("util.relative_dates.today", return_value=TODAY):
            self.assertEqual(relative_dates.as_iso_date("5h ago"), "2026-03-28")

    def test_a_bare_month_letter_is_not_read_as_months(self):
        """"3mo" must not lex as three minutes and a stray letter."""
        with patch("util.relative_dates.today", return_value=TODAY):
            self.assertEqual(relative_dates.as_iso_date("3m ago"), "2026-03-28")
            self.assertEqual(relative_dates.as_iso_date("3mo ago"), "2025-12-28")

    def test_passthrough_non_relative(self):
        self.assertEqual(relative_dates.as_iso_date("2026-01-15"), "2026-01-15")

    def test_passthrough_empty(self):
        self.assertEqual(relative_dates.as_iso_date(""), "")

    def test_an_unknown_unit_comes_back_untouched(self):
        self.assertEqual(relative_dates.as_iso_date("2y ago"), "2y ago")

    def test_the_day_is_read_without_a_clock_so_today_is_the_answer(self):
        """Whatever the real time was, an hours-ago page read today is today —
        the pages give no clock time, so a crossed midnight is not recoverable."""
        with patch("util.relative_dates.today", return_value=TODAY):
            self.assertEqual(relative_dates.as_iso_date("23h ago"), TODAY.isoformat())


if __name__ == "__main__":
    unittest.main()
