"""Tests for the stats window and stacked area chart."""

from unittest.mock import patch

import pytest

from PyQt6.QtGui import QFontMetrics, QImage

from gui.run_record import RunRecord
from gui.stats_window import (
    STAGE_COLORS,
    StackedAreaChart,
    StatsWindow,
    _legend_font,
    _pick_y_ticks,
    chart_right_margin,
    legend_width,
)
from tasks.stages import ALL_STAGES, STAGE_LABELS
from tests.color_support import band_fill
from tests.temp_helpers import make_run_record


def _make_record(
    stage_durations: dict[str, float], started_at: str = "2026-03-30T00:00:00",
) -> RunRecord:
    """Build a minimal RunRecord with the given stage durations."""
    stages = [
        {"name": name, "status": "completed", "duration_seconds": dur}
        for name, dur in stage_durations.items()
    ]
    return make_run_record(
        id="test",
        started_at=started_at,
        finished_at="2026-03-30T00:00:01",
        duration_seconds=sum(stage_durations.values()),
        trigger="manual",
        stages=stages,
    )


_UNPAINTED = (255, 0, 255)  # the sentinel _render fills with; paintEvent covers it
_WHITE = (255, 255, 255)


def _render(chart, w: int = 800, h: int = 400) -> QImage:
    """Render the chart into an image, which enters paintEvent even offscreen.

    ``repaint()`` on a widget that was never shown dispatches no paint event at
    all on the offscreen platform, which is how four earlier "does not crash"
    tests covered none of the drawing code. The image starts magenta so a
    paintEvent that returns without painting is distinguishable from white.
    """
    chart.resize(w, h)
    image = QImage(w, h, QImage.Format.Format_ARGB32)
    image.fill(0xFFFF00FF)
    chart.render(image)
    return image


def _rgb(image: QImage, x: int, y: int) -> tuple[int, int, int]:
    return image.pixelColor(x, y).getRgb()[:3]


def _ink_count(image: QImage, xs: range, ys: range) -> int:
    """Pixels in the region that are neither the white ground nor unpainted."""
    return sum(
        1
        for y in ys
        for x in xs
        if _rgb(image, x, y) not in (_WHITE, _UNPAINTED)
    )


def _is_band_fill(pixel: tuple[int, int, int], stage_key: str) -> bool:
    """Whether *pixel* is *stage_key*'s band fill, within a rounding step.

    Qt's alpha blend and this file's arithmetic can round a channel apart, and
    pinning the exact rounding would fail on a raster-engine change that no
    user could see.
    """
    expected = band_fill(STAGE_COLORS[stage_key])
    return all(abs(p - e) <= 1 for p, e in zip(pixel, expected))


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
        purge_series = series[ALL_STAGES.index("purge")]
        assert purge_series == [1.0, 2.0, 3.0]

    def test_every_stage_charts_its_own_durations(self, chart):
        series = chart._compute_series()
        sort_series = series[ALL_STAGES.index("sort")]
        assert sort_series == [2.0, 4.0, 6.0]

    def test_missing_stage_returns_zero(self, chart):
        series = chart._compute_series()
        # "metadata" is a stage the records here do not mention
        metadata_series = series[ALL_STAGES.index("metadata")]
        assert metadata_series == [0.0, 0.0, 0.0]

    def test_averages_returns_running_mean(self, chart):
        chart.set_mode("averages")
        series = chart._compute_series()
        purge_series = series[ALL_STAGES.index("purge")]
        # raw = [1, 2, 3], running avg = [1/1, 3/2, 6/3] = [1.0, 1.5, 2.0]
        assert purge_series == pytest.approx([1.0, 1.5, 2.0])

    def test_averages_mode_means_every_stage_not_just_the_first(self, chart):
        chart.set_mode("averages")
        series = chart._compute_series()
        sort_series = series[ALL_STAGES.index("sort")]
        # raw = [2, 4, 6], running avg = [2/1, 6/2, 12/3] = [2.0, 3.0, 4.0]
        assert sort_series == pytest.approx([2.0, 3.0, 4.0])


class TestStackedAreaChartEdgeCases:
    def test_empty_records(self):
        chart = StackedAreaChart([])
        series = chart._compute_series()
        for s in series:
            assert s == []


def _two_runs(stage_durations_old, stage_durations_new):
    """Two records a day apart, newest first, the order load_runs returns."""
    return [
        _make_record(stage_durations_new, started_at="2026-03-31T00:00:00"),
        _make_record(stage_durations_old, started_at="2026-03-30T00:00:00"),
    ]


def _limit_line_rows(image: QImage) -> list[int]:
    """Rows in the 10-minute line's neighbourhood holding a long gray dash run.

    At the default 700 s scale the dotted line lands at y = 67; antialiasing
    splits it across two rows of mid-gray. Sixty gray pixels across the chart's
    middle cannot come from any band, whose colors are never gray.
    """
    rows = []
    for y in range(55, 81):
        grays = sum(
            1
            for x in range(100, 640)
            if (lambda c: c[0] == c[1] == c[2] and 150 <= c[0] <= 235)(_rgb(image, x, y))
        )
        if grays >= 60:
            rows.append(y)
    return rows


class TestStackedAreaChartPainting:
    """What the rendered chart shows.

    Four earlier tests called ``repaint()`` on a widget that was never shown,
    which dispatches no paint event offscreen; a ``raise`` at the top of
    paintEvent left all four green. Everything here goes through ``_render``,
    which does enter paintEvent, and asserts on the ink that comes out.
    """

    def test_a_run_paints_each_stage_as_a_band_of_its_own_color(self):
        chart = StackedAreaChart(
            _two_runs({"purge": 200.0, "sort": 200.0}, {"purge": 200.0, "sort": 200.0})
        )
        image = _render(chart)
        # purge is the first stage in the registry, so its band is the bottom
        # 200 s of the stack and sort's — the next stage these records mention —
        # is the 200 s above it.
        assert _is_band_fill(_rgb(image, 380, 300), "purge")
        assert _is_band_fill(_rgb(image, 380, 230), "sort")
        assert _rgb(image, 380, 120) == _WHITE  # above the stack: bare ground

    def test_an_empty_chart_says_so_instead_of_going_blank(self):
        image = _render(StackedAreaChart([]))
        assert _ink_count(image, range(71, 690, 2), range(21, 350, 2)) > 20

    def test_fit_mode_rescales_the_bands_to_fill_the_chart(self):
        # 50 s of work is 7 % of the fixed 700 s scale -- a sliver at the very
        # bottom. Fit mode rescales to the tallest run plus headroom, so the
        # same band then covers most of the chart's height.
        normal = _render(StackedAreaChart(_two_runs({"sort": 50.0}, {"sort": 50.0})))
        fitted_chart = StackedAreaChart(_two_runs({"sort": 50.0}, {"sort": 50.0}))
        fitted_chart.set_fit(True)
        fitted = _render(fitted_chart)
        assert _rgb(normal, 380, 185) == _WHITE
        assert _is_band_fill(_rgb(fitted, 380, 185), "sort")

    def test_averages_mode_charts_the_running_mean_not_the_raw_run(self):
        # sort runs 100 s then 300 s: the second run's raw band reaches 300 s,
        # its running mean only 200 s, so a pixel between the two heights near
        # the newest run is inked in one mode and bare in the other.
        normal = _render(StackedAreaChart(_two_runs({"sort": 100.0}, {"sort": 300.0})))
        averaged_chart = StackedAreaChart(_two_runs({"sort": 100.0}, {"sort": 300.0}))
        averaged_chart.set_mode("averages")
        averaged = _render(averaged_chart)
        # Just inside the chart's right edge, which the legend's measured width
        # decides -- a fixed x here would land in the margin on another font.
        newest = 800 - chart_right_margin() - 10
        assert _is_band_fill(_rgb(normal, newest, 230), "sort")
        assert _rgb(averaged, newest, 230) == _WHITE

    def test_the_10_minute_line_appears_only_when_the_scale_reaches_it(self):
        tall = _render(StackedAreaChart(_two_runs({"sort": 100.0}, {"sort": 300.0})))
        assert _limit_line_rows(tall), "no dotted 10-minute line at the 700 s scale"
        # Fit mode over 50 s runs scales to ~57 s, far short of 600 s
        fitted_chart = StackedAreaChart(_two_runs({"sort": 50.0}, {"sort": 50.0}))
        fitted_chart.set_fit(True)
        fitted = _render(fitted_chart)
        assert not _limit_line_rows(fitted)

    def test_the_legend_swatches_every_stage_in_its_chart_color(self):
        image = _render(StackedAreaChart(_two_runs({"sort": 100.0}, {"sort": 300.0})))
        margin_pixels = {
            _rgb(image, x, y)
            for x in range(800 - chart_right_margin(), 800)
            for y in range(20, 350)
        }
        for stage_key in ALL_STAGES:
            color = STAGE_COLORS[stage_key]
            assert (color.red(), color.green(), color.blue()) in margin_pixels, (
                f"legend has no swatch for {stage_key!r}"
            )

    def test_the_legend_names_each_stage_rather_than_its_key(self):
        """Patching the labels to nothing takes the legend's words with them,
        which is what says the words come from the label table and not from
        the keys the chart iterates."""
        chart = StackedAreaChart(_two_runs({"sort": 100.0}, {"sort": 300.0}))
        text_band = (
            range(800 - chart_right_margin() + 26, 795),
            range(20, 20 + 16 * 13),
        )

        named = _ink_count(_render(chart), *text_band)
        with patch.dict(
            "gui.stats_window.STAGE_LABELS",
            {key: "" for key in STAGE_LABELS},
            clear=True,
        ):
            blank = _ink_count(_render(chart), *text_band)

        assert named > blank + 100

    def test_the_legend_is_wide_enough_for_the_longest_label(self):
        """The words are up to half again the width of the keys they replaced,
        and by how much is the machine's font's business, so the box is
        measured from them rather than set to a number picked on one box."""
        metrics = QFontMetrics(_legend_font())
        widest = max(metrics.horizontalAdvance(label) for label in STAGE_LABELS.values())

        assert legend_width() >= widest + 22

    def test_the_runs_are_dated_along_the_x_axis(self):
        image = _render(StackedAreaChart(_two_runs({"sort": 100.0}, {"sort": 300.0})))
        assert _ink_count(image, range(60, 740, 2), range(352, 380)) > 50


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
    """The tick rule: a handful of round values, not a wall of gridlines."""

    _NICE_STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 180, 300, 600)

    def _assert_readable(self, ticks, y_max):
        assert 3 <= len(ticks) <= 7, f"{len(ticks)} ticks is not a readable axis"
        assert all(0 < t <= y_max for t in ticks)
        steps = {b - a for a, b in zip(ticks, ticks[1:])}
        assert len(steps) == 1, f"uneven tick spacing {sorted(steps)}"
        assert steps <= set(self._NICE_STEPS)

    def test_full_scale(self):
        ticks = _pick_y_ticks(700.0)
        assert 600 in ticks
        self._assert_readable(ticks, 700.0)

    def test_small_scale(self):
        self._assert_readable(_pick_y_ticks(10.0), 10.0)

    def test_medium_scale(self):
        self._assert_readable(_pick_y_ticks(45.0), 45.0)


class TestStatsActionExists:
    def test_tray_has_stats_action(self):
        from gui.tray import EvolverTray
        tray = EvolverTray()
        assert tray.stats_action is not None

    def test_window_has_stats_action(self):
        from gui.main_window import EvolverMainWindow
        window = EvolverMainWindow()
        assert window.stats_action is not None

    # The receivers()-count wiring assertion that used to live here is replaced
    # by TestToolbarAppWiring's stats tests in test_main_window_controls.py,
    # which trigger the real actions and assert a StatsWindow opens.
