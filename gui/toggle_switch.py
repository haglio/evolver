"""Custom toggle switch widget for the toolbar."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter
from PyQt6.QtWidgets import QWidget

_TRACK_W = 44
_TRACK_H = 22
_KNOB_MARGIN = 2
_KNOB_D = _TRACK_H - 2 * _KNOB_MARGIN

_COLOR_ON = QColor(0x30, 0x80, 0xE0)
_COLOR_OFF = QColor(0xB0, 0xB0, 0xB0)
_COLOR_KNOB = QColor(255, 255, 255)


class ToggleSwitch(QWidget):
    """A visual on/off toggle switch."""

    clicked = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(_TRACK_W, _TRACK_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, on: bool):
        if self._checked != on:
            self._checked = on
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(_TRACK_W, _TRACK_H)

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.update()
        self.clicked.emit(self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Track
        track_color = _COLOR_ON if self._checked else _COLOR_OFF
        p.setBrush(QBrush(track_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, _TRACK_W, _TRACK_H), _TRACK_H / 2, _TRACK_H / 2)

        # Knob
        knob_x = _TRACK_W - _KNOB_MARGIN - _KNOB_D if self._checked else _KNOB_MARGIN
        p.setBrush(QBrush(_COLOR_KNOB))
        p.drawEllipse(QRectF(knob_x, _KNOB_MARGIN, _KNOB_D, _KNOB_D))

        p.end()
