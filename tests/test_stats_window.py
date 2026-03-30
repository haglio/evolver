"""Tests for the stats window and stacked area chart."""

import unittest
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from gui.run_record import RunRecord
from gui.stats_window import StackedAreaChart, StatsWindow, _pick_y_ticks

_app = QApplication.instance() or QApplication([])


def _make_record(stage_durations: dict[str, float]) -> RunRecord:
    """Build a minimal RunRecord with the given stage durations."""
    stages = [
        {"name": name, "status": "completed", "duration_seconds": dur}
        for name, dur in stage_durations.items()
    ]
    return RunRecord(
        id="test",
        started_at="2026-03-30T00:00:00",
        finished_at="2026-03-30T00:00:01",
        duration_seconds=sum(stage_durations.values()),
        trigger="manual",
        status="success",
        stages=stages,
    )


class TestStackedAreaChartSeries(unittest.TestCase):
    """_compute_series should return correct values for normal and averages mode."""

    def setUp(self):
        # Three records with known durations (newest-first like load_runs returns)
        self.records = [
            _make_record({"sort": 6.0, "purge": 3.0}),
            _make_record({"sort": 4.0, "purge": 2.0}),
            _make_record({"sort": 2.0, "purge": 1.0}),
        ]
        self.chart = StackedAreaChart(self.records)

    def test_normal_returns_raw_durations_chronological(self):
        series = self.chart._compute_series()
        # Records are reversed to chronological, so sort values = [2, 4, 6]
        sort_series = series[0]  # sort is first in ALL_STAGES
        self.assertEqual(sort_series, [2.0, 4.0, 6.0])

    def test_normal_returns_raw_for_second_stage(self):
        series = self.chart._compute_series()
        purge_series = series[1]  # purge is second
        self.assertEqual(purge_series, [1.0, 2.0, 3.0])

    def test_missing_stage_returns_zero(self):
        series = self.chart._compute_series()
        # "scripts" is third stage but not in our records
        scripts_series = series[2]
        self.assertEqual(scripts_series, [0.0, 0.0, 0.0])

    def test_averages_returns_running_mean(self):
        self.chart.set_mode("averages")
        series = self.chart._compute_series()
        sort_series = series[0]
        # raw = [2, 4, 6], running avg = [2/1, 6/2, 12/3] = [2.0, 3.0, 4.0]
        self.assertAlmostEqual(sort_series[0], 2.0)
        self.assertAlmostEqual(sort_series[1], 3.0)
        self.assertAlmostEqual(sort_series[2], 4.0)

    def test_averages_second_stage(self):
        self.chart.set_mode("averages")
        series = self.chart._compute_series()
        purge_series = series[1]
        # raw = [1, 2, 3], running avg = [1.0, 1.5, 2.0]
        self.assertAlmostEqual(purge_series[0], 1.0)
        self.assertAlmostEqual(purge_series[1], 1.5)
        self.assertAlmostEqual(purge_series[2], 2.0)

    def test_set_mode_triggers_update(self):
        with patch.object(self.chart, "update") as mock_update:
            self.chart.set_mode("averages")
            mock_update.assert_called_once()

    def test_set_fit_triggers_update(self):
        with patch.object(self.chart, "update") as mock_update:
            self.chart.set_fit(True)
            mock_update.assert_called_once()


class TestStackedAreaChartEdgeCases(unittest.TestCase):
    def test_empty_records(self):
        chart = StackedAreaChart([])
        series = chart._compute_series()
        for s in series:
            self.assertEqual(s, [])

    def test_paint_does_not_crash_with_data(self):
        records = [_make_record({"sort": 1.0})]
        chart = StackedAreaChart(records)
        chart.resize(800, 400)
        chart.repaint()  # should not raise

    def test_paint_does_not_crash_empty(self):
        chart = StackedAreaChart([])
        chart.resize(800, 400)
        chart.repaint()

    def test_paint_does_not_crash_fit_mode(self):
        records = [_make_record({"sort": 1.0, "purge": 2.0})]
        chart = StackedAreaChart(records)
        chart.set_fit(True)
        chart.resize(800, 400)
        chart.repaint()


class TestStatsWindow(unittest.TestCase):
    def test_window_title(self):
        window = StatsWindow([])
        self.assertIn("Statistics", window.windowTitle())

    def test_normal_button_starts_checked(self):
        window = StatsWindow([])
        self.assertTrue(window._normal_btn.isChecked())
        self.assertFalse(window._averages_btn.isChecked())

    def test_toggle_to_averages(self):
        records = [_make_record({"sort": 1.0})]
        window = StatsWindow(records)
        window._averages_btn.click()
        self.assertTrue(window._averages_btn.isChecked())
        self.assertFalse(window._normal_btn.isChecked())

    def test_toggle_back_to_normal(self):
        records = [_make_record({"sort": 1.0})]
        window = StatsWindow(records)
        window._averages_btn.click()
        window._normal_btn.click()
        self.assertTrue(window._normal_btn.isChecked())
        self.assertFalse(window._averages_btn.isChecked())

    def test_10m_button_starts_checked(self):
        window = StatsWindow([])
        self.assertTrue(window._10m_btn.isChecked())
        self.assertFalse(window._fit_btn.isChecked())

    def test_toggle_to_fit(self):
        records = [_make_record({"sort": 1.0})]
        window = StatsWindow(records)
        window._fit_btn.click()
        self.assertTrue(window._fit_btn.isChecked())
        self.assertFalse(window._10m_btn.isChecked())

    def test_toggle_back_to_10m(self):
        records = [_make_record({"sort": 1.0})]
        window = StatsWindow(records)
        window._fit_btn.click()
        window._10m_btn.click()
        self.assertTrue(window._10m_btn.isChecked())
        self.assertFalse(window._fit_btn.isChecked())

    def test_empty_records_shows_placeholder(self):
        window = StatsWindow([])
        self.assertIsNone(window._chart)


class TestPickYTicks(unittest.TestCase):
    def test_full_scale(self):
        ticks = _pick_y_ticks(700.0)
        self.assertIn(600, ticks)
        self.assertNotIn(0, ticks)

    def test_small_scale(self):
        ticks = _pick_y_ticks(10.0)
        self.assertTrue(all(t <= 10.0 for t in ticks))
        self.assertTrue(len(ticks) >= 2)

    def test_medium_scale(self):
        ticks = _pick_y_ticks(45.0)
        self.assertTrue(all(t <= 45.0 for t in ticks))


class TestStatsActionExists(unittest.TestCase):
    def test_tray_has_stats_action(self):
        from gui.tray import EvolverTray
        tray = EvolverTray()
        self.assertIsNotNone(tray.stats_action)

    def test_window_has_stats_action(self):
        from gui.main_window import EvolverMainWindow
        window = EvolverMainWindow()
        self.assertIsNotNone(window.stats_action)

    def test_app_connects_stats_actions(self):
        from gui.app import EvolverApp
        with patch("gui.app.QApplication", return_value=_app):
            app = EvolverApp()
        self.assertTrue(
            app._window.stats_action.receivers(app._window.stats_action.triggered) > 0
        )
        self.assertTrue(
            app._tray.stats_action.receivers(app._tray.stats_action.triggered) > 0
        )


if __name__ == "__main__":
    unittest.main()
