"""Restart wears the family's mark, in the window and in the tray alike."""

import unittest

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon, QImage, QPainter, QPixmap, QColor
from PyQt6.QtWidgets import QApplication

from gui.icons import restart_icon
from shared_ui.icons import glyph_pixmap

_app = QApplication.instance() or QApplication([])

_SIZE = QSize(48, 48)


def _rendered(icon: QIcon) -> QImage:
    return icon.pixmap(_SIZE, QIcon.Mode.Normal).toImage()


class TestRestartIcon(unittest.TestCase):

    def test_it_is_the_familys_restart_mark(self):
        # Not Font Awesome's "redo": that is a plain circular arrow, which is
        # what an undo looks like everywhere else here. The family draws this
        # control as a power symbol whose ring runs on into an arrowhead.
        self.assertEqual(
            _rendered(restart_icon("#ddd")),
            glyph_pixmap("restart", 48, QColor("#ddd")).toImage(),
        )

    def test_it_takes_the_ink_the_chrome_it_sits_on_needs(self):
        # The toolbar is dark and the tray menu is light, so one drawing has to
        # come out in two inks rather than being baked to one.
        light = _rendered(restart_icon("#ddd"))
        dark = _rendered(restart_icon("#333"))
        self.assertNotEqual(light, dark)
        self.assertEqual(dark, glyph_pixmap("restart", 48, QColor("#333")).toImage())

    def test_it_dims_when_the_action_is_disabled(self):
        # Qt swaps to the disabled rendering itself, so it has to be there --
        # qtawesome's icon carried only the one mode.
        icon = restart_icon("#ddd")
        disabled = icon.pixmap(_SIZE, QIcon.Mode.Disabled)
        self.assertFalse(disabled.isNull())
        self.assertNotEqual(disabled.toImage(), _rendered(icon))

    def test_the_mark_actually_draws(self):
        # A named glyph that paints nothing gives a menu row an empty square and
        # raises nothing at all.
        canvas = QPixmap(48, 48)
        canvas.fill(QColor(0, 0, 0, 0))
        painter = QPainter(canvas)
        painter.drawPixmap(0, 0, restart_icon("#ddd").pixmap(_SIZE, QIcon.Mode.Normal))
        painter.end()
        image = canvas.toImage()
        inked = sum(
            1
            for y in range(48)
            for x in range(48)
            if image.pixelColor(x, y).alpha() > 32
        )
        self.assertGreater(inked, 100)
