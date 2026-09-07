"""Stats window with a stacked area chart of pipeline stage durations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.run_record import RunRecord
from tasks.stages import ALL_STAGES, STAGE_LABELS, STAGES

# The registry's colors, as the painter wants them. This is the edge where Qt
# begins: the declaration holds plain RGB so the headless pipeline can read it.
STAGE_COLORS = {stage.key: QColor(*stage.color) for stage in STAGES}

_Y_MAX = 700.0  # seconds — keeps the 600s line near the top
_LIMIT_SECONDS = 600.0
_MARGIN_LEFT = 70
_MARGIN_TOP = 20
_MARGIN_LOWER = 50

# What a band is painted with. Named because the tests compare stage colors as
# the bands the eye actually sees — translucent over white, which draws them
# closer together than the colors themselves are.
BAND_ALPHA = 180

_LEGEND_POINT_SIZE = 8
_LEGEND_SWATCH = 10
_LEGEND_PADDING = 6
_LEGEND_TEXT_GAP = 6
_LEGEND_LINE_HEIGHT = 16
_LEGEND_INSET = 10  # between the legend panel and both the chart and the widget edge


def _legend_font() -> QFont:
    font = QFont()
    font.setPointSize(_LEGEND_POINT_SIZE)
    return font


def legend_width() -> int:
    """The legend panel's width: enough for the longest stage label, measured.

    Not a fixed number, because the labels run half again the width of the
    stage keys they replaced and by how much depends on the machine's font —
    a number picked here would clip the legend wherever that font is wider.
    """
    metrics = QFontMetrics(_legend_font())
    widest = max(metrics.horizontalAdvance(label) for label in STAGE_LABELS.values())
    return _LEGEND_PADDING + _LEGEND_SWATCH + _LEGEND_TEXT_GAP + widest + _LEGEND_PADDING


def chart_right_margin() -> int:
    """What the legend costs the chart: its own width, inset from both sides."""
    return legend_width() + 2 * _LEGEND_INSET


def _pick_y_ticks(y_max: float) -> list[float]:
    """Choose ~5 nice round tick values spanning (0, y_max], skipping 0."""
    nice = [1, 2, 5, 10, 15, 30, 60, 120, 180, 300, 600]
    # Pick the interval that gives closest to 5 ticks
    best_step = nice[-1]
    for step in nice:
        count = int(y_max // step)
        if count >= 3:
            best_step = step
            if count <= 7:
                break
    ticks = []
    val = best_step
    while val <= y_max:
        ticks.append(val)
        val += best_step
    return ticks


def _label_count(chart_w: int) -> int:
    """How many dates fit along an axis this wide, between two and a dozen."""
    return min(12, max(2, chart_w // 70))


def _x_axis_labels(t_min: float, t_max: float, count: int) -> list[str]:
    """*count* evenly spaced dates across the span, disambiguated by time.

    A library that ran the pipeline every ten minutes puts several labels on
    one date, and a row of identical dates says nothing about where a run sits;
    those get their clock time on a second line. A label with a distinct date
    does not, because the date is the thing being read.
    """
    span = t_max - t_min or 1.0
    moments = [datetime.fromtimestamp(t_min + span * i / (count - 1))
               for i in range(count)]
    dates = [moment.strftime("%m/%d") for moment in moments]
    return [
        moment.strftime("%m/%d\n%H:%M")
        if dates.count(date) > 1 else date
        for moment, date in zip(moments, dates, strict=True)
    ]


def _duration_of(record: RunRecord, stage_key: str) -> float:
    """How long *stage_key* took in *record* -- zero when it did not run."""
    for stage in record.stages:
        if stage.get("name") == stage_key:
            return stage.get("duration_seconds", 0.0)
    return 0.0


def _running_means(values: list[float]) -> list[float]:
    """The mean of everything up to and including each value."""
    means: list[float] = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        means.append(total / (index + 1))
    return means


@dataclass(frozen=True)
class _Plot:
    """Where the chart sits in the widget, and how a value becomes a pixel."""

    left: int
    top: int
    width: int
    height: int
    timestamps: list[float]
    series: list[list[float]]
    y_max: float

    @property
    def t_min(self) -> float:
        return min(self.timestamps, default=0.0)

    @property
    def t_max(self) -> float:
        return max(self.timestamps, default=0.0)

    def x_of(self, run_index: int) -> float:
        """Where the run at *run_index* sits, by when it ran."""
        span = self.t_max - self.t_min or 1.0
        return self.left + self.width * (self.timestamps[run_index] - self.t_min) / span

    def y_of(self, seconds: float) -> float:
        return self.top + self.height * (1 - seconds / self.y_max)


class StackedAreaChart(QWidget):
    """Custom-painted stacked area chart of stage durations across runs."""

    def __init__(self, records: list[RunRecord], parent=None):
        super().__init__(parent)
        self._records = list(reversed(records))  # chronological order
        self._mode = "normal"
        self._fit = False
        self.setMinimumSize(600, 400)

    def set_mode(self, mode: str):
        self._mode = mode
        self.update()

    def set_fit(self, fit: bool):
        self._fit = fit
        self.update()

    def _compute_series(self) -> list[list[float]]:
        """One list of values per stage, one value per run, oldest first."""
        return [self._values_for(stage_key) for stage_key in ALL_STAGES]

    def _values_for(self, stage_key: str) -> list[float]:
        """What one stage's band is drawn from: its seconds, or its trend.

        Averages mode is a running mean rather than the whole history's, so a
        stage that has been getting slower shows as a band that climbs -- the
        one number cannot.
        """
        durations = [_duration_of(record, stage_key) for record in self._records]
        return _running_means(durations) if self._mode == "averages" else durations

    def _parse_timestamps(self) -> list[float]:
        """Parse started_at into epoch seconds for each record."""
        timestamps: list[float] = []
        for rec in self._records:
            try:
                dt = datetime.fromisoformat(rec.started_at)
            except (ValueError, TypeError):
                dt = datetime(2000, 1, 1)
            timestamps.append(dt.timestamp())
        return timestamps

    def paintEvent(self, event):
        """The chart, in the order the layers sit: ground, bands, then axes.

        Each layer is its own function taking the one :class:`_Plot` that says
        where the chart is and how a value becomes a pixel. It was a single
        method holding the geometry, the scale, the stacking, both axes, the
        tick rule and the legend in one set of locals -- so the widget's whole
        drawing had to be read to change any of it, and the only thing that
        could be tested was the pixels that came out.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(255, 255, 255))

        plot = self._plot()
        if plot is None:
            painter.end()
            return
        if not self._records:
            painter.setPen(QColor(0x80, 0x80, 0x80))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No run data")
            painter.end()
            return

        self._paint_bands(painter, plot)
        self._paint_limit_line(painter, plot)
        self._paint_y_axis(painter, plot)
        self._paint_x_axis(painter, plot)
        self._draw_legend(painter, self.width(), plot.top)
        painter.end()

    def _plot(self) -> _Plot | None:
        """Where the chart sits and how a run and a duration become a point.

        None when the widget is too small to hold one, which is the only case
        the drawing below cannot handle.
        """
        chart_w = self.width() - _MARGIN_LEFT - chart_right_margin()
        chart_h = self.height() - _MARGIN_TOP - _MARGIN_LOWER
        if chart_w <= 0 or chart_h <= 0:
            return None

        timestamps = self._parse_timestamps()
        series = self._compute_series()
        return _Plot(
            left=_MARGIN_LEFT,
            top=_MARGIN_TOP,
            width=chart_w,
            height=chart_h,
            timestamps=timestamps,
            series=series,
            y_max=self._y_max(series),
        )

    def _y_max(self, series: list[list[float]]) -> float:
        """The top of the scale: the watchdog's ceiling, or the tallest run.

        The fixed scale is what makes two runs comparable at a glance -- a band
        the same height means the same seconds, on any chart. Fit mode gives
        that up on purpose, for a library whose runs are all far below it.
        """
        if not self._fit:
            return _Y_MAX
        tallest = max((sum(stage[i] for stage in series)
                       for i in range(len(self._records))), default=0.0)
        return max(tallest * 1.15, 1.0)  # 15% headroom

    def _paint_bands(self, painter: QPainter, plot: _Plot):
        """One filled band per stage, stacked in registry order."""
        baselines = [0.0] * len(plot.timestamps)
        for stage_idx, stage_key in enumerate(ALL_STAGES):
            values = plot.series[stage_idx]
            color = STAGE_COLORS[stage_key]

            path = QPainterPath()
            path.moveTo(plot.x_of(0), plot.y_of(baselines[0]))
            for i in range(1, len(plot.timestamps)):
                path.lineTo(plot.x_of(i), plot.y_of(baselines[i]))
            for i in reversed(range(len(plot.timestamps))):
                path.lineTo(plot.x_of(i), plot.y_of(baselines[i] + values[i]))
            path.closeSubpath()

            fill = QColor(color)
            fill.setAlpha(BAND_ALPHA)
            painter.setBrush(fill)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)

            painter.setPen(QPen(color, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(len(plot.timestamps) - 1):
                painter.drawLine(
                    int(plot.x_of(i)), int(plot.y_of(baselines[i] + values[i])),
                    int(plot.x_of(i + 1)), int(plot.y_of(baselines[i + 1] + values[i + 1])),
                )

            for i in range(len(plot.timestamps)):
                baselines[i] += values[i]

    def _paint_limit_line(self, painter: QPainter, plot: _Plot):
        """The watchdog's ten minutes, dotted -- only when the scale reaches it."""
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        if plot.y_max < _LIMIT_SECONDS:
            return
        limit_y = int(plot.y_of(_LIMIT_SECONDS))
        painter.setPen(QPen(QColor(0x80, 0x80, 0x80), 1, Qt.PenStyle.DotLine))
        painter.drawLine(plot.left, limit_y, plot.left + plot.width, limit_y)
        painter.setPen(QColor(0x80, 0x80, 0x80))
        painter.drawText(plot.left + plot.width - 40, limit_y - 4, "10 min")

    def _paint_y_axis(self, painter: QPainter, plot: _Plot):
        """The duration ticks, their labels, and the rotated axis name."""
        painter.setPen(QColor(0x60, 0x60, 0x60))
        for secs in _pick_y_ticks(plot.y_max):
            y = int(plot.y_of(secs))
            painter.drawLine(plot.left - 4, y, plot.left, y)
            painter.drawText(plot.left - 35, y + 4,
                             f"{secs / 60:.0f}m" if secs >= 60 else f"{secs:.0f}s")

        painter.save()
        painter.setPen(QColor(0x50, 0x50, 0x50))
        label_font = QFont()
        label_font.setPointSize(9)
        painter.setFont(label_font)
        painter.translate(14, plot.top + plot.height // 2)
        painter.rotate(-90)
        painter.drawText(-40, 0, "run duration")
        painter.restore()

    def _paint_x_axis(self, painter: QPainter, plot: _Plot):
        """The baseline, the left border, and the dates under the runs."""
        baseline_y = int(plot.y_of(0))
        painter.setPen(QColor(0xA0, 0xA0, 0xA0))
        painter.drawLine(plot.left, baseline_y, plot.left + plot.width, baseline_y)
        painter.drawLine(plot.left, plot.top, plot.left, baseline_y)

        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor(0x60, 0x60, 0x60))
        labels = _x_axis_labels(plot.t_min, plot.t_max, _label_count(plot.width))
        for i, label in enumerate(labels):
            x = int(plot.left + plot.width * i / (len(labels) - 1))
            date, _, time = label.partition("\n")
            painter.drawText(x - 15, baseline_y + 14, date)
            if time:
                painter.drawText(x - 12, baseline_y + 26, time)

    def _draw_legend(self, painter: QPainter, widget_w: int, top_y: int):
        painter.setFont(_legend_font())

        swatch_size = _LEGEND_SWATCH
        line_height = _LEGEND_LINE_HEIGHT
        padding = _LEGEND_PADDING
        legend_w = legend_width()

        lx = widget_w - legend_w - _LEGEND_INSET
        ly = int(top_y + 10)

        legend_h = len(ALL_STAGES) * line_height + padding * 2

        bg = QColor(255, 255, 255, 220)
        painter.setBrush(bg)
        painter.setPen(QColor(0xC0, 0xC0, 0xC0))
        painter.drawRect(lx, ly, legend_w, legend_h)

        for i, stage_key in enumerate(ALL_STAGES):
            color = STAGE_COLORS[stage_key]
            y_pos = ly + padding + i * line_height
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(lx + padding, y_pos, swatch_size, swatch_size)
            painter.setPen(QColor(0x30, 0x30, 0x30))
            painter.drawText(lx + padding + swatch_size + _LEGEND_TEXT_GAP,
                             y_pos + swatch_size - 1, STAGE_LABELS[stage_key])


def _toggle(label: str, *, checked: bool = False) -> QPushButton:
    button = QPushButton(label)
    button.setCheckable(True)
    button.setChecked(checked)
    return button


def _either_or(parent, *buttons: QPushButton) -> QButtonGroup:
    """A group where exactly one of *buttons* is checked, whichever is clicked."""
    group = QButtonGroup(parent)
    group.setExclusive(True)
    for button in buttons:
        group.addButton(button)
    return group


class StatsWindow(QDialog):
    """Non-modal dialog showing pipeline run statistics."""

    def __init__(self, records: list[RunRecord], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Evolver \u2014 Run Statistics")
        self.setMinimumSize(800, 500)
        self.resize(1000, 600)

        layout = QVBoxLayout(self)

        # Two either-or pairs: what the bands measure, and what the scale is.
        # Held exclusive by Qt rather than by four slots that each checked one
        # button and unchecked the other by hand.
        btn_row = QHBoxLayout()
        self._normal_btn = _toggle("Normal", checked=True)
        self._averages_btn = _toggle("Averages")
        self._10m_btn = _toggle("10m", checked=True)
        self._fit_btn = _toggle("Fit")
        self._measure = _either_or(self, self._normal_btn, self._averages_btn)
        self._scale = _either_or(self, self._10m_btn, self._fit_btn)
        for button in (self._normal_btn, self._averages_btn):
            btn_row.addWidget(button)
        btn_row.addSpacing(20)
        for button in (self._10m_btn, self._fit_btn):
            btn_row.addWidget(button)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        if records:
            self._chart = StackedAreaChart(records)
            layout.addWidget(self._chart, stretch=1)
        else:
            self._chart = None
            placeholder = QLabel("No run data available.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(placeholder, stretch=1)

        self._measure.buttonClicked.connect(self._on_measure_chosen)
        self._scale.buttonClicked.connect(self._on_scale_chosen)

    def _on_measure_chosen(self, button):
        if self._chart is not None:
            self._chart.set_mode(
                "averages" if button is self._averages_btn else "normal")

    def _on_scale_chosen(self, button):
        if self._chart is not None:
            self._chart.set_fit(button is self._fit_btn)
