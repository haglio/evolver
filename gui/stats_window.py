"""Stats window with a stacked area chart of pipeline stage durations."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.progress import ALL_STAGES
from gui.run_record import RunRecord

STAGE_COLORS = {
    "sort": QColor(0x4E, 0x79, 0xA7),
    "purge": QColor(0xF2, 0x8E, 0x2B),
    "scripts": QColor(0xE1, 0x57, 0x59),
    "clip_scripts": QColor(0xD3, 0x7A, 0x9C),
    "bookmarks": QColor(0x76, 0xB7, 0xB2),
    "metadata": QColor(0x59, 0xA1, 0x4F),
    "upscale": QColor(0xED, 0xC9, 0x48),
    "upscale_non_ai": QColor(0x9C, 0x75, 0x5F),
    "group_non_ai": QColor(0x8C, 0xD1, 0x7D),
    "references": QColor(0xA0, 0xCB, 0xE8),
    "dupes": QColor(0xB0, 0x7A, 0xA1),
    "verify": QColor(0xFF, 0x9D, 0xA7),
}

_Y_MAX = 700.0  # seconds — keeps the 600s line near the top
_LIMIT_SECONDS = 600.0
_MARGIN_LEFT = 70
_MARGIN_RIGHT = 110
_MARGIN_TOP = 20
_MARGIN_BOTTOM = 50


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
        """Return one list of floats per stage, one value per run.

        In normal mode the values are raw durations.  In averages mode
        each value is the running cumulative mean up to that run.
        """
        n = len(self._records)
        series: list[list[float]] = []
        for stage_key in ALL_STAGES:
            raw = []
            for rec in self._records:
                dur = 0.0
                for s in rec.stages:
                    if s.get("name") == stage_key:
                        dur = s.get("duration_seconds", 0.0)
                        break
                raw.append(dur)

            if self._mode == "averages":
                avgs: list[float] = []
                cumsum = 0.0
                for i, v in enumerate(raw):
                    cumsum += v
                    avgs.append(cumsum / (i + 1))
                series.append(avgs)
            else:
                series.append(raw)
        return series

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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        chart_x = _MARGIN_LEFT
        chart_y = _MARGIN_TOP
        chart_w = w - _MARGIN_LEFT - _MARGIN_RIGHT
        chart_h = h - _MARGIN_TOP - _MARGIN_BOTTOM

        if chart_w <= 0 or chart_h <= 0:
            painter.end()
            return

        n = len(self._records)

        # Background
        painter.fillRect(self.rect(), QColor(255, 255, 255))

        if n == 0:
            painter.setPen(QColor(0x80, 0x80, 0x80))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No run data")
            painter.end()
            return

        series = self._compute_series()
        timestamps = self._parse_timestamps()
        t_min = min(timestamps)
        t_max = max(timestamps)
        t_range = t_max - t_min or 1.0

        if self._fit:
            # Compute max stacked total across all runs
            max_stack = 0.0
            for i in range(n):
                total = sum(s[i] for s in series)
                max_stack = max(max_stack, total)
            y_max = max(max_stack * 1.15, 1.0)  # 15% headroom
        else:
            y_max = _Y_MAX

        def to_x(t: float) -> float:
            return chart_x + chart_w * (t - t_min) / t_range

        def to_y(val: float) -> float:
            return chart_y + chart_h * (1 - val / y_max)

        # Cumulative baselines for stacking
        prev_cum = [0.0] * n

        for stage_idx, stage_key in enumerate(ALL_STAGES):
            vals = series[stage_idx]
            color = STAGE_COLORS.get(stage_key, QColor(0x80, 0x80, 0x80))

            path = QPainterPath()
            path.moveTo(to_x(timestamps[0]), to_y(prev_cum[0]))
            for i in range(1, n):
                path.lineTo(to_x(timestamps[i]), to_y(prev_cum[i]))
            for i in range(n - 1, -1, -1):
                path.lineTo(to_x(timestamps[i]), to_y(prev_cum[i] + vals[i]))
            path.closeSubpath()

            fill = QColor(color)
            fill.setAlpha(180)
            painter.setBrush(fill)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)

            painter.setPen(QPen(color, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(n - 1):
                painter.drawLine(
                    int(to_x(timestamps[i])),
                    int(to_y(prev_cum[i] + vals[i])),
                    int(to_x(timestamps[i + 1])),
                    int(to_y(prev_cum[i + 1] + vals[i + 1])),
                )

            for i in range(n):
                prev_cum[i] += vals[i]

        # 10-minute dotted line (only if visible)
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        if _LIMIT_SECONDS <= y_max:
            limit_y = int(to_y(_LIMIT_SECONDS))
            pen = QPen(QColor(0x80, 0x80, 0x80), 1, Qt.PenStyle.DotLine)
            painter.setPen(pen)
            painter.drawLine(chart_x, limit_y, chart_x + chart_w, limit_y)
            painter.setPen(QColor(0x80, 0x80, 0x80))
            painter.drawText(chart_x + chart_w - 40, limit_y - 4, "10 min")

        # Y-axis ticks and labels
        painter.setPen(QColor(0x60, 0x60, 0x60))
        tick_values = _pick_y_ticks(y_max)
        for secs in tick_values:
            y = int(to_y(secs))
            painter.drawLine(chart_x - 4, y, chart_x, y)
            if secs >= 60:
                painter.drawText(chart_x - 35, y + 4, f"{secs / 60:.0f}m")
            else:
                painter.drawText(chart_x - 35, y + 4, f"{secs:.0f}s")

        # Y-axis label (rotated)
        painter.save()
        painter.setPen(QColor(0x50, 0x50, 0x50))
        label_font = QFont()
        label_font.setPointSize(9)
        painter.setFont(label_font)
        mid_y = chart_y + chart_h // 2
        painter.translate(14, mid_y)
        painter.rotate(-90)
        painter.drawText(-40, 0, "run duration")
        painter.restore()

        # X-axis line
        painter.setPen(QColor(0xA0, 0xA0, 0xA0))
        baseline_y = int(to_y(0))
        painter.drawLine(chart_x, baseline_y, chart_x + chart_w, baseline_y)

        # X-axis date labels
        self._draw_x_labels(painter, t_min, t_max, chart_x, chart_w, baseline_y)

        # Chart border (left axis)
        painter.setPen(QColor(0xA0, 0xA0, 0xA0))
        painter.drawLine(chart_x, chart_y, chart_x, baseline_y)

        # Legend (in right margin, outside chart area)
        self._draw_legend(painter, w, chart_y)

        painter.end()

    def _draw_x_labels(self, painter: QPainter, t_min: float, t_max: float,
                       chart_x: int, chart_w: int, baseline_y: int):
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor(0x60, 0x60, 0x60))

        num_labels = min(12, max(2, chart_w // 70))
        t_range = t_max - t_min or 1.0

        label_times: list[float] = []
        for i in range(num_labels):
            t = t_min + t_range * i / (num_labels - 1)
            label_times.append(t)

        # Format as dates, add times where dates collide
        dates = [datetime.fromtimestamp(t) for t in label_times]
        date_strs = [d.strftime("%m/%d") for d in dates]

        # Check for duplicate dates — add time to disambiguate
        labels: list[str] = []
        for i, ds in enumerate(date_strs):
            needs_time = False
            if i > 0 and date_strs[i - 1] == ds:
                needs_time = True
            if i < len(date_strs) - 1 and date_strs[i + 1] == ds:
                needs_time = True
            if needs_time:
                labels.append(dates[i].strftime("%m/%d\n%H:%M"))
            else:
                labels.append(ds)

        for i, label in enumerate(labels):
            x = int(chart_x + chart_w * i / (num_labels - 1))
            lines = label.split("\n")
            painter.drawText(x - 15, baseline_y + 14, lines[0])
            if len(lines) > 1:
                painter.drawText(x - 12, baseline_y + 26, lines[1])

    def _draw_legend(self, painter: QPainter, widget_w: int, top_y: int):
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)

        box_size = 10
        line_height = 16
        padding = 6
        legend_w = _MARGIN_RIGHT - 20

        lx = widget_w - _MARGIN_RIGHT + 10
        ly = int(top_y + 10)

        legend_h = len(ALL_STAGES) * line_height + padding * 2

        bg = QColor(255, 255, 255, 220)
        painter.setBrush(bg)
        painter.setPen(QColor(0xC0, 0xC0, 0xC0))
        painter.drawRect(lx, ly, legend_w, legend_h)

        for i, stage_key in enumerate(ALL_STAGES):
            color = STAGE_COLORS.get(stage_key, QColor(0x80, 0x80, 0x80))
            y_pos = ly + padding + i * line_height
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(lx + padding, y_pos, box_size, box_size)
            painter.setPen(QColor(0x30, 0x30, 0x30))
            painter.drawText(lx + padding + box_size + 6, y_pos + box_size - 1, stage_key)


class StatsWindow(QDialog):
    """Non-modal dialog showing pipeline run statistics."""

    def __init__(self, records: list[RunRecord], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Evolver \u2014 Run Statistics")
        self.setMinimumSize(800, 500)
        self.resize(1000, 600)

        layout = QVBoxLayout(self)

        # Toggle buttons
        btn_row = QHBoxLayout()
        self._normal_btn = QPushButton("Normal")
        self._normal_btn.setCheckable(True)
        self._normal_btn.setChecked(True)
        self._averages_btn = QPushButton("Averages")
        self._averages_btn.setCheckable(True)
        btn_row.addWidget(self._normal_btn)
        btn_row.addWidget(self._averages_btn)
        btn_row.addSpacing(20)
        self._10m_btn = QPushButton("10m")
        self._10m_btn.setCheckable(True)
        self._10m_btn.setChecked(True)
        self._fit_btn = QPushButton("Fit")
        self._fit_btn.setCheckable(True)
        btn_row.addWidget(self._10m_btn)
        btn_row.addWidget(self._fit_btn)
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

        self._normal_btn.clicked.connect(self._on_normal)
        self._averages_btn.clicked.connect(self._on_averages)
        self._10m_btn.clicked.connect(self._on_10m)
        self._fit_btn.clicked.connect(self._on_fit)

    def _on_normal(self):
        self._normal_btn.setChecked(True)
        self._averages_btn.setChecked(False)
        if self._chart:
            self._chart.set_mode("normal")

    def _on_averages(self):
        self._averages_btn.setChecked(True)
        self._normal_btn.setChecked(False)
        if self._chart:
            self._chart.set_mode("averages")

    def _on_10m(self):
        self._10m_btn.setChecked(True)
        self._fit_btn.setChecked(False)
        if self._chart:
            self._chart.set_fit(False)

    def _on_fit(self):
        self._fit_btn.setChecked(True)
        self._10m_btn.setChecked(False)
        if self._chart:
            self._chart.set_fit(True)
