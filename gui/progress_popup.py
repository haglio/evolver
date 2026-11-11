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
from shared_ui.fonts import SIZE_BODY
from shared_ui.spacing import MARGIN_DIALOG

from evolver import ALL_STAGES, STAGE_LABELS

_CAPTION_GUTTER = 12
BAR_WIDTH = 200


def _caption_width(font) -> int:
    metrics = QFontMetrics(font)
    return max(metrics.horizontalAdvance(label) for label in STAGE_LABELS.values()) + _CAPTION_GUTTER


class ProgressPopup(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Evolver - Pipeline Progress")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowCloseButtonHint
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_DIALOG, MARGIN_DIALOG, MARGIN_DIALOG, MARGIN_DIALOG)

        header = QLabel("Pipeline Progress")
        font = header.font()
        font.setPointSize(SIZE_BODY)
        font.setBold(True)
        header.setFont(font)
        layout.addWidget(header)

        self._bars: dict[str, QProgressBar] = {}
        self._stage_values: dict[str, int] = {}

        caption_width = _caption_width(self.font())
        for key in ALL_STAGES:
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

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        total_layout = QHBoxLayout()
        total_label = QLabel("Total")
        total_label.setFixedWidth(caption_width)
        total_font = total_label.font()
        total_font.setBold(True)
        total_label.setFont(total_font)
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
