from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QRectF, Qt
from PyQt6.QtGui import QAction, QPainter
from PyQt6.QtWidgets import QMenu
from shared_ui.colors import BG_TERTIARY
from shared_ui.spacing import MARGIN_STANDARD
from shared_ui.toggle_switch import ToggleSwitch

_OUTLINE = 2


class MenuWithSwitches(QMenu):

    def __init__(self):
        super().__init__()
        self._switches: dict[QAction, ToggleSwitch] = {}

    def put_switch_on(self, action: QAction, switch: ToggleSwitch) -> None:
        switch.resize(switch.sizeHint())
        switch.toggled.connect(lambda _on: self.update())
        self._switches[action] = switch
        room = self._width_of_a_row_holding(action) + MARGIN_STANDARD + switch.width()
        self.setMinimumWidth(max(self.minimumWidth(), room))

    def _width_of_a_row_holding(self, action: QAction) -> int:
        alone = QMenu()
        alone.setStyleSheet(self.styleSheet())
        alone.addAction(action)
        return alone.sizeHint().width()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for action, switch in self._switches.items():
            row = self.actionGeometry(action)
            place = QRect(QPoint(row.right() - MARGIN_STANDARD - switch.width(),
                                 row.center().y() - switch.height() // 2), switch.size())
            if action is self.activeAction():
                self._outline(painter, place)
            switch.render(painter, place.topLeft())
        painter.end()

    @staticmethod
    def _outline(painter: QPainter, place: QRect) -> None:
        ring = QRectF(place).adjusted(-_OUTLINE, -_OUTLINE, _OUTLINE, _OUTLINE)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BG_TERTIARY)
        painter.drawRoundedRect(ring, ring.height() / 2, ring.height() / 2)
