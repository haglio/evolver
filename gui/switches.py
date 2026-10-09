from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QAction, QPainter, QPen, QPixmap, QRegion
from PyQt6.QtWidgets import QMenu, QToolButton, QWidget
from shared_ui.chrome import toolbar_padding
from shared_ui.colors import TOGGLE_HANDLE
from shared_ui.spacing import BUTTON_ICON, BUTTON_PAD_H_TIGHT, MARGIN_STANDARD
from shared_ui.toggle_switch import ToggleSwitch


def _draw_at_the_end(painter: QPainter, switch: ToggleSwitch, row: QRect, inset: int) -> QRectF:
    pixel_ratio = painter.device().devicePixelRatioF()
    picture = _picture_of(switch, pixel_ratio)
    corner = QPoint(row.right() - inset - switch.width(), row.center().y() - switch.height() // 2)
    painter.drawPixmap(corner, picture)
    pill = QRectF(QRegion(picture.mask()).boundingRect())
    return QRectF(pill.topLeft() / pixel_ratio, pill.size() / pixel_ratio).translated(QPointF(corner))


def _outline(painter: QPainter, pill: QRectF) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(TOGGLE_HANDLE, 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    edge = pill.adjusted(0.5, 0.5, -0.5, -0.5)
    painter.drawRoundedRect(edge, edge.height() / 2, edge.height() / 2)


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
            pill = _draw_at_the_end(painter, switch, self.actionGeometry(action), MARGIN_STANDARD)
            if action is self.activeAction():
                _outline(painter, pill)
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
