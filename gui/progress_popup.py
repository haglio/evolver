"""Floating popup window showing pipeline progress with per-stage bars."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from gui.progress import ALL_STAGES, STAGE_DISPLAY_NAMES


class ProgressPopup(QWidget):
    """Floating progress window with per-stage bars and a total bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Evolver - Pipeline Progress")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setFixedWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        header = QLabel("Pipeline Progress")
        font = header.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        header.setFont(font)
        layout.addWidget(header)

        self._bars: dict[str, QProgressBar] = {}
        self._stage_values: dict[str, int] = {}

        for key in ALL_STAGES:
            row_layout = QHBoxLayout()
            label = QLabel(STAGE_DISPLAY_NAMES.get(key, key))
            label.setFixedWidth(160)
            row_layout.addWidget(label)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFixedHeight(18)
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
        total_label.setFixedWidth(160)
        total_font = total_label.font()
        total_font.setBold(True)
        total_label.setFont(total_font)
        total_layout.addWidget(total_label)

        self._total_bar = QProgressBar()
        self._total_bar.setRange(0, 800)
        self._total_bar.setValue(0)
        self._total_bar.setFixedHeight(20)
        self._total_bar.setTextVisible(True)
        self._total_bar.setFormat("%p%")
        total_layout.addWidget(self._total_bar, stretch=1)

        layout.addLayout(total_layout)

    def on_stage_started(self, name: str):
        if name in self._bars:
            bar = self._bars[name]
            bar.setRange(0, 0)  # indeterminate

    def on_stage_completed(self, name: str, result: object, elapsed: float, status: str):
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
        """Show the popup centered on *anchor*'s visible area."""
        self.adjustSize()
        center = anchor.frameGeometry().center()
        x = center.x() - self.width() // 2
        y = center.y() - self.height() // 2
        self.move(x, y)
        self.show()
