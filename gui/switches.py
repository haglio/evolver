from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QAction, QPainter, QPixmap, QRegion
from PyQt6.QtWidgets import QMenu, QToolButton, QWidget
from shared_ui.spacing import BUTTON_ICON, BUTTON_PAD_H_TIGHT, MARGIN_STANDARD
from shared_ui.toggle_switch import ToggleSwitch

from gui.toolbar_style import toolbar_padding


def _draw_at_the_end(painter: QPainter, switch: ToggleSwitch, row: QRect, inset: int) -> None:
    painter.drawPixmap(QPoint(row.right() - inset - switch.width(),
                              row.center().y() - switch.height() // 2),
                       _picture_of(switch, painter.device().devicePixelRatioF()))


def _picture_of(switch: ToggleSwitch, pixel_ratio: float) -> QPixmap:
    picture = QPixmap(switch.size() * pixel_ratio)
    picture.setDevicePixelRatio(pixel_ratio)
    picture.fill(Qt.GlobalColor.transparent)
    switch.render(picture, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return picture


def _repaint_on_toggle(switch: ToggleSwitch, widget) -> None:
    switch.resize(switch.sizeHint())
    switch.toggled.connect(lambda _on: widget.update())


class MenuWithSwitches(QMenu):

    def __init__(self):
        super().__init__()
        self._switches: dict[QAction, ToggleSwitch] = {}

    def put_switch_on(self, action: QAction, switch: ToggleSwitch) -> None:
        _repaint_on_toggle(switch, self)
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
            _draw_at_the_end(painter, switch, self.actionGeometry(action), MARGIN_STANDARD)
        painter.end()


class SwitchButton(QToolButton):

    def __init__(self, action: QAction, switch: ToggleSwitch):
        super().__init__()
        self.setDefaultAction(action)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIconSize(QSize(BUTTON_ICON, BUTTON_ICON))
        self.setAutoRaise(True)
        _repaint_on_toggle(switch, self)
        self._switch = switch
        self.setStyleSheet(
            toolbar_padding(right=MARGIN_STANDARD + switch.width() + BUTTON_PAD_H_TIGHT))

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        _draw_at_the_end(painter, self._switch, self.rect(), BUTTON_PAD_H_TIGHT)
        painter.end()
