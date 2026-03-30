"""Stats window with a stacked area chart of pipeline stage durations."""

from __future__ import annotations

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

from gui.progress import ALL_STAGES, STAGE_DISPLAY_NAMES
from gui.run_record import RunRecord

STAGE_COLORS = {
    "sort": QColor(0x4E, 0x79, 0xA7),
    "purge": QColor(0xF2, 0x8E, 0x2B),
    "scripts": QColor(0xE1, 0x57, 0x59),
    "bookmarks": QColor(0x76, 0xB7, 0xB2),
    "metadata": QColor(0x59, 0xA1, 0x4F),
    "upscale": QColor(0xED, 0xC9, 0x48),
    "dupes": QColor(0xB0, 0x7A, 0xA1),
    "verify": QColor(0xFF, 0x9D, 0xA7),
}

_Y_MAX = 700.0  # seconds — keeps the 600s line near the top
_LIMIT_SECONDS = 600.0
_MARGIN_LEFT = 60
_MARGIN_RIGHT = 20
_MARGIN_TOP = 20
_MARGIN_BOTTOM = 40


class StackedAreaChart(QWidget):
    """Custom-painted stacked area chart of stage durations across runs."""

    def __init__(self, records: list[RunRecord], parent=None):
        super().__init__(parent)
        self._records = list(reversed(records))  # chronological order
        self._mode = "normal"
        self.setMinimumSize(600, 400)

    def set_mode(self, mode: str):
        self._mode = mode
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
        x_scale = chart_w / max(n - 1, 1)

        def to_x(i: int) -> float:
            return chart_x + i * x_scale

        def to_y(val: float) -> float:
            return chart_y + chart_h * (1 - val / _Y_MAX)

        # Cumulative baselines for stacking
        prev_cum = [0.0] * n

        for stage_idx, stage_key in enumerate(ALL_STAGES):
            vals = series[stage_idx]
            color = STAGE_COLORS.get(stage_key, QColor(0x80, 0x80, 0x80))

            path = QPainterPath()
            # Bottom edge (left to right along previous cumulative)
            path.moveTo(to_x(0), to_y(prev_cum[0]))
            for i in range(1, n):
                path.lineTo(to_x(i), to_y(prev_cum[i]))
            # Top edge (right to left along new cumulative)
            for i in range(n - 1, -1, -1):
                path.lineTo(to_x(i), to_y(prev_cum[i] + vals[i]))
            path.closeSubpath()

            fill = QColor(color)
            fill.setAlpha(180)
            painter.setBrush(fill)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)

            # Top edge outline
            painter.setPen(QPen(color, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(n - 1):
                painter.drawLine(
                    int(to_x(i)),
                    int(to_y(prev_cum[i] + vals[i])),
                    int(to_x(i + 1)),
                    int(to_y(prev_cum[i + 1] + vals[i + 1])),
                )

            for i in range(n):
                prev_cum[i] += vals[i]

        # 10-minute dotted line
        limit_y = int(to_y(_LIMIT_SECONDS))
        pen = QPen(QColor(0x80, 0x80, 0x80), 1, Qt.PenStyle.DotLine)
        painter.setPen(pen)
        painter.drawLine(chart_x, limit_y, chart_x + chart_w, limit_y)
        painter.setPen(QColor(0x80, 0x80, 0x80))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(chart_x + chart_w - 40, limit_y - 4, "10 min")

        # Y-axis ticks and labels
        painter.setPen(QColor(0x60, 0x60, 0x60))
        tick_intervals = [0, 120, 240, 360, 480, 600]
        for secs in tick_intervals:
            y = int(to_y(secs))
            painter.drawLine(chart_x - 4, y, chart_x, y)
            label = f"{secs // 60}m" if secs >= 60 else "0"
            painter.drawText(chart_x - 35, y + 4, label)

        # X-axis line
        painter.setPen(QColor(0xA0, 0xA0, 0xA0))
        baseline_y = int(to_y(0))
        painter.drawLine(chart_x, baseline_y, chart_x + chart_w, baseline_y)

        # X-axis labels (every Nth run)
        if n > 1:
            step = max(1, n // 10)
            for i in range(0, n, step):
                x = int(to_x(i))
                painter.drawText(x - 5, baseline_y + 15, str(i + 1))

        # Chart border (left and bottom axes)
        painter.setPen(QColor(0xA0, 0xA0, 0xA0))
        painter.drawLine(chart_x, chart_y, chart_x, baseline_y)

        # Legend
        self._draw_legend(painter, chart_x + chart_w, chart_y)

        painter.end()

    def _draw_legend(self, painter: QPainter, right_x: float, top_y: float):
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)

        box_size = 10
        line_height = 16
        padding = 6
        legend_w = 140
        legend_h = len(ALL_STAGES) * line_height + padding * 2

        lx = int(right_x - legend_w - 10)
        ly = int(top_y + 10)

        # Background
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
            display = STAGE_DISPLAY_NAMES.get(stage_key, stage_key)
            painter.drawText(lx + padding + box_size + 6, y_pos + box_size - 1, display)


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
