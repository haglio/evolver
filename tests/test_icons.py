"""Quit, restart and Run Now wear the family's marks, in the window and the tray."""

import unittest

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon, QImage, QPainter, QPixmap, QColor
from PyQt6.QtWidgets import QApplication

from gui.icons import quit_icon, restart_icon, run_now_icon
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


class TestQuitIcon(unittest.TestCase):

    def test_it_is_the_familys_power_mark(self):
        # Fun Time paints this same one on its bar, and the two apps are open
        # together -- so quit has to be one drawing, not two weights of one idea.
        self.assertEqual(
            _rendered(quit_icon("#ddd")),
            glyph_pixmap("power", 48, QColor("#ddd")).toImage(),
        )

    def test_restart_reads_as_its_relative(self):
        # Restart is built from quit's own ring and stroke with the ring running
        # on into an arrowhead. Side by side in a menu they must look related --
        # and still be told apart, which the arrowhead is for.
        quit_ink = _ink(quit_icon("#ddd"))
        restart_ink = _ink(restart_icon("#ddd"))

        self.assertNotEqual(_rendered(quit_icon("#ddd")), _rendered(restart_icon("#ddd")))
        # Within a quarter of each other's weight: two unrelated marks would not be.
        self.assertLess(abs(quit_ink - restart_ink) / quit_ink, 0.25)


class TestRunNowIcon(unittest.TestCase):

    def test_it_is_the_familys_play_triangle(self):
        self.assertEqual(
            _rendered(run_now_icon("#ddd")),
            glyph_pixmap("play", 48, QColor("#ddd")).toImage(),
        )

    def test_its_corners_are_rounded(self):
        # A hard-pointed triangle reads as a sharper, lighter mark than the ones
        # beside it -- which is what the user saw against Fun Time's.
        from shared_ui.icon_geometry import GLYPHS, Polygon

        triangle = next(s for s in GLYPHS["play"] if isinstance(s, Polygon))
        self.assertGreater(triangle.round_radius, 0)


def _ink(icon: QIcon) -> int:
    image = _rendered(icon)
    return sum(
        1
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 32
    )
