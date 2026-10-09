from __future__ import annotations

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QAction, QPainter
from PyQt6.QtWidgets import QMenu
from shared_ui.spacing import MARGIN_STANDARD
from shared_ui.toggle_switch import ToggleSwitch


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
        for action, switch in self._switches.items():
            row = self.actionGeometry(action)
            switch.render(painter, QPoint(row.right() - MARGIN_STANDARD - switch.width(),
                                          row.center().y() - switch.height() // 2))
        painter.end()
