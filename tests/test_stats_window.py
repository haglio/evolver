"""Tests for the stats window and stacked area chart."""

from unittest.mock import patch

import pytest

from gui.run_record import RunRecord
from gui.stats_window import StackedAreaChart, StatsWindow, _pick_y_ticks
from tests.gui_support import build_evolver_app


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


class TestStackedAreaChartSeries:
    """_compute_series should return correct values for normal and averages mode."""

    @pytest.fixture
    def chart(self):
        # Three records with known durations (newest-first like load_runs returns)
        records = [
            _make_record({"sort": 6.0, "purge": 3.0}),
            _make_record({"sort": 4.0, "purge": 2.0}),
            _make_record({"sort": 2.0, "purge": 1.0}),
        ]
        return StackedAreaChart(records)

    def test_normal_returns_raw_durations_chronological(self, chart):
        series = chart._compute_series()
        # Records are reversed to chronological, so purge values = [1, 2, 3]
        purge_series = series[0]  # purge is first in ALL_STAGES
        assert purge_series == [1.0, 2.0, 3.0]

    def test_every_stage_charts_its_own_durations(self, chart):
        series = chart._compute_series()
        sort_series = series[2]  # sort is third (after purge, metadata)
        assert sort_series == [2.0, 4.0, 6.0]

    def test_missing_stage_returns_zero(self, chart):
        series = chart._compute_series()
        # "metadata" is second stage but not in our records
        metadata_series = series[1]
        assert metadata_series == [0.0, 0.0, 0.0]

    def test_averages_returns_running_mean(self, chart):
        chart.set_mode("averages")
        series = chart._compute_series()
        purge_series = series[0]
        # raw = [1, 2, 3], running avg = [1/1, 3/2, 6/3] = [1.0, 1.5, 2.0]
        assert purge_series == pytest.approx([1.0, 1.5, 2.0])

    def test_averages_mode_means_every_stage_not_just_the_first(self, chart):
        chart.set_mode("averages")
        series = chart._compute_series()
        sort_series = series[2]  # sort is third (after purge, metadata)
        # raw = [2, 4, 6], running avg = [2/1, 6/2, 12/3] = [2.0, 3.0, 4.0]
        assert sort_series == pytest.approx([2.0, 3.0, 4.0])

    def test_set_mode_triggers_update(self, chart):
        with patch.object(chart, "update") as mock_update:
            chart.set_mode("averages")
            mock_update.assert_called_once()

    def test_set_fit_triggers_update(self, chart):
        with patch.object(chart, "update") as mock_update:
            chart.set_fit(True)
            mock_update.assert_called_once()


class TestStackedAreaChartEdgeCases:
    def test_empty_records(self):
        chart = StackedAreaChart([])
        series = chart._compute_series()
        for s in series:
            assert s == []

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


class TestStatsWindow:
    def test_window_title(self):
        window = StatsWindow([])
        assert "Statistics" in window.windowTitle()

    def test_normal_button_starts_checked(self):
        window = StatsWindow([])
        assert window._normal_btn.isChecked()
        assert not window._averages_btn.isChecked()

    def test_toggle_to_averages(self):
        records = [_make_record({"sort": 1.0})]
        window = StatsWindow(records)
        window._averages_btn.click()
        assert window._averages_btn.isChecked()
        assert not window._normal_btn.isChecked()

    def test_toggle_back_to_normal(self):
        records = [_make_record({"sort": 1.0})]
        window = StatsWindow(records)
        window._averages_btn.click()
        window._normal_btn.click()
        assert window._normal_btn.isChecked()
        assert not window._averages_btn.isChecked()

    def test_10m_button_starts_checked(self):
        window = StatsWindow([])
        assert window._10m_btn.isChecked()
        assert not window._fit_btn.isChecked()

    def test_toggle_to_fit(self):
        records = [_make_record({"sort": 1.0})]
        window = StatsWindow(records)
        window._fit_btn.click()
        assert window._fit_btn.isChecked()
        assert not window._10m_btn.isChecked()

    def test_toggle_back_to_10m(self):
        records = [_make_record({"sort": 1.0})]
        window = StatsWindow(records)
        window._fit_btn.click()
        window._10m_btn.click()
        assert window._10m_btn.isChecked()
        assert not window._fit_btn.isChecked()

    def test_empty_records_shows_placeholder(self):
        window = StatsWindow([])
        assert window._chart is None


class TestPickYTicks:
    def test_full_scale(self):
        ticks = _pick_y_ticks(700.0)
        assert 600 in ticks
        assert 0 not in ticks

    def test_small_scale(self):
        ticks = _pick_y_ticks(10.0)
        assert all(t <= 10.0 for t in ticks)
        assert len(ticks) >= 2

    def test_medium_scale(self):
        ticks = _pick_y_ticks(45.0)
        assert all(t <= 45.0 for t in ticks)


class TestStatsActionExists:
    def test_tray_has_stats_action(self):
        from gui.tray import EvolverTray
        tray = EvolverTray()
        assert tray.stats_action is not None

    def test_window_has_stats_action(self):
        from gui.main_window import EvolverMainWindow
        window = EvolverMainWindow()
        assert window.stats_action is not None

    def test_app_connects_stats_actions(self, request):
        app = build_evolver_app(request)
        assert app._window.stats_action.receivers(app._window.stats_action.triggered) > 0
        assert app._tray.stats_action.receivers(app._tray.stats_action.triggered) > 0
