from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)
from shared_ui.spacing import GAP_DIALOG, MARGIN_DIALOG

from evolver import ALL_STAGES, SECTIONS, STAGE_LABELS

_CAPTION_GUTTER = 12
BAR_WIDTH = 200


def _caption_width(font) -> int:
    metrics = QFontMetrics(font)
    return max(metrics.horizontalAdvance(label) for label in STAGE_LABELS.values()) + _CAPTION_GUTTER


def _heading(text: str) -> QLabel:
    heading = QLabel(text)
    font = heading.font()
    font.setBold(True)
    heading.setFont(font)
    return heading


def _line() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


class ProgressPopup(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Evolver - Pipeline progress")
        self.setWindowFlags(Qt.WindowType.Window)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_DIALOG, MARGIN_DIALOG, MARGIN_DIALOG, MARGIN_DIALOG)

        layout.addWidget(_heading("Pipeline progress"))

        self._bars: dict[str, QProgressBar] = {}
        self._stage_values: dict[str, int] = {}

        caption_width = _caption_width(self.font())
        for number, section in enumerate(SECTIONS):
            if number:
                layout.addSpacing(GAP_DIALOG)
            layout.addWidget(_heading(section.heading))
            layout.addWidget(_line())
            for key in (stage.key for stage in section.stages):
                row_layout = QHBoxLayout()
                label = QLabel(STAGE_LABELS[key])
                label.setFixedWidth(caption_width)
                row_layout.addWidget(label)

                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(0)
                bar.setFixedHeight(18)
                bar.setMinimumWidth(BAR_WIDTH)
                bar.setTextVisible(True)
                row_layout.addWidget(bar, stretch=1)

                layout.addLayout(row_layout)
                self._bars[key] = bar
                self._stage_values[key] = 0

        layout.addWidget(_line())

        total_layout = QHBoxLayout()
        total_label = _heading("Total")
        total_label.setFixedWidth(caption_width)
        total_layout.addWidget(total_label)

        self._total_bar = QProgressBar()
        self._total_bar.setRange(0, 100 * len(ALL_STAGES))
        self._total_bar.setValue(0)
        self._total_bar.setFixedHeight(20)
        self._total_bar.setMinimumWidth(BAR_WIDTH)
        self._total_bar.setTextVisible(True)
        self._total_bar.setFormat("%p%")
        total_layout.addWidget(self._total_bar, stretch=1)

        layout.addLayout(total_layout)

    def on_stage_started(self, name: str):
        if name in self._bars:
            bar = self._bars[name]
            bar.setRange(0, 0)

    def on_stage_completed(self, name: str):
        if name not in self._bars:
            return
        bar = self._bars[name]
        bar.setRange(0, 100)
        bar.setValue(100)
        self._stage_values[name] = 100
        self._update_total()

    def on_stage_progress(self, name: str, current: int, total: int):
        if name not in self._bars:
            return
        bar = self._bars[name]
        if bar.maximum() == 0:
            bar.setRange(0, 100)
        value = int(current / total * 100) if total > 0 else 0
        bar.setValue(value)
        self._stage_values[name] = value
        self._update_total()

    def on_pipeline_finished(self):
        QTimer.singleShot(2000, self.close)

    def _update_total(self):
        self._total_bar.setValue(sum(self._stage_values.values()))

    def show_over(self, anchor: QWidget):
        self.adjustSize()
        center = anchor.frameGeometry().center()
        x = center.x() - self.width() // 2
        y = center.y() - self.height() // 2
        self.move(x, y)
        self.show()
