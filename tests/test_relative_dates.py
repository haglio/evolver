from __future__ import annotations

import datetime
import unittest
from unittest.mock import patch

from util import relative_dates

TODAY_THE_28TH = datetime.date(2026, 3, 28)


class TestAsIsoDate(unittest.TestCase):
    def test_days_ago(self):
        with patch("util.relative_dates.today", return_value=TODAY_THE_28TH):
            assert relative_dates.as_iso_date("2d ago") == "2026-03-26"

    def test_weeks_ago(self):
        with patch("util.relative_dates.today", return_value=TODAY_THE_28TH):
            assert relative_dates.as_iso_date("2w ago") == "2026-03-14"

    def test_months_ago_from_the_28th_lands_on_a_day_every_month_has(self):
        with patch("util.relative_dates.today", return_value=TODAY_THE_28TH):
            assert relative_dates.as_iso_date("3mo ago") == "2025-12-28"

    def test_months_ago_from_the_31st_clamps_to_the_shorter_months_last_day(self):
        with patch("util.relative_dates.today", return_value=datetime.date(2026, 3, 31)):
            assert relative_dates.as_iso_date("1mo ago") == "2026-02-28"

    def test_months_ago_across_a_december_boundary_clamps_too(self):
        with patch("util.relative_dates.today", return_value=datetime.date(2026, 1, 31)):
            assert relative_dates.as_iso_date("1mo ago") == "2025-12-31"

    def test_minutes_ago(self):
        with patch("util.relative_dates.today", return_value=TODAY_THE_28TH):
            assert relative_dates.as_iso_date("5m ago") == "2026-03-28"

    def test_hours_ago(self):
        with patch("util.relative_dates.today", return_value=TODAY_THE_28TH):
            assert relative_dates.as_iso_date("5h ago") == "2026-03-28"

    def test_a_bare_month_letter_is_not_read_as_months(self):
        with patch("util.relative_dates.today", return_value=TODAY_THE_28TH):
            assert relative_dates.as_iso_date("3m ago") == "2026-03-28"
            assert relative_dates.as_iso_date("3mo ago") == "2025-12-28"

    def test_passthrough_non_relative(self):
        assert relative_dates.as_iso_date("2026-01-15") == "2026-01-15"

    def test_passthrough_empty(self):
        assert relative_dates.as_iso_date("") == ""

    def test_an_unknown_unit_comes_back_untouched(self):
        assert relative_dates.as_iso_date("2y ago") == "2y ago"

    def test_the_day_is_read_without_a_clock_so_today_is_the_answer(self):
        with patch("util.relative_dates.today", return_value=TODAY_THE_28TH):
            assert relative_dates.as_iso_date("23h ago") == TODAY_THE_28TH.isoformat()


if __name__ == "__main__":
    unittest.main()
