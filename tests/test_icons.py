"""Quit, restart and Run Now wear the family's marks, in the window and the tray.

What evolver owns here is which glyph each function asks shared_ui for, and
that the caller's ink color reaches the drawing. How the glyphs are drawn --
their geometry, their disabled rendering, their relative ink weights -- is
shared_ui's contract, pinned in shared_ui's own suite; re-asserting it here
turned a legitimate glyph redesign into a red evolver suite.
"""

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QIcon, QImage

from gui.icons import quit_icon, restart_icon, run_now_icon
from shared_ui.icons import glyph_pixmap


_SIZE = QSize(48, 48)


def _rendered(icon: QIcon) -> QImage:
    return icon.pixmap(_SIZE, QIcon.Mode.Normal).toImage()


class TestRestartIcon:

    def test_it_is_the_familys_restart_mark(self):
        # Not Font Awesome's "redo": that is a plain circular arrow, which is
        # what an undo looks like everywhere else here. The family draws this
        # control as a power symbol whose ring runs on into an arrowhead.
        assert _rendered(restart_icon("#ddd")) == glyph_pixmap("restart", 48, QColor("#ddd")).toImage()

    def test_it_takes_the_ink_the_chrome_it_sits_on_needs(self):
        # The toolbar is dark and the tray menu is light, so one drawing has to
        # come out in two inks rather than being baked to one.
        light = _rendered(restart_icon("#ddd"))
        dark = _rendered(restart_icon("#333"))
        assert light != dark
        assert dark == glyph_pixmap("restart", 48, QColor("#333")).toImage()


class TestQuitIcon:

    def test_it_is_the_familys_power_mark(self):
        # Fun Time paints this same one on its bar, and the two apps are open
        # together -- so quit has to be one drawing, not two weights of one idea.
        assert _rendered(quit_icon("#ddd")) == glyph_pixmap("power", 48, QColor("#ddd")).toImage()


class TestRunNowIcon:

    def test_it_is_the_familys_play_triangle(self):
        assert _rendered(run_now_icon("#ddd")) == glyph_pixmap("play", 48, QColor("#ddd")).toImage()
