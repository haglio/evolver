from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QIcon, QImage
from shared_ui.icons import icon_pixmap

from gui.icons import pause_icon, quit_icon, restart_icon, run_now_icon

_SIZE = QSize(48, 48)


def _rendered(icon: QIcon) -> QImage:
    return icon.pixmap(_SIZE, QIcon.Mode.Normal).toImage()


class TestRestartIcon:

    def test_it_is_the_familys_restart_mark(self):
        assert _rendered(restart_icon("#ddd")) == icon_pixmap("restart", 48, QColor("#ddd")).toImage()

    def test_it_takes_the_ink_the_chrome_it_sits_on_needs(self):
        light = _rendered(restart_icon("#ddd"))
        dark = _rendered(restart_icon("#333"))
        assert light != dark
        assert dark == icon_pixmap("restart", 48, QColor("#333")).toImage()


class TestQuitIcon:

    def test_it_is_the_familys_power_mark(self):
        assert _rendered(quit_icon("#ddd")) == icon_pixmap("power", 48, QColor("#ddd")).toImage()


class TestRunNowIcon:

    def test_it_is_the_familys_play_triangle(self):
        assert _rendered(run_now_icon("#ddd")) == icon_pixmap("play", 48, QColor("#ddd")).toImage()


class TestPauseIcon:

    def test_it_is_the_familys_pause_bars(self):
        assert _rendered(pause_icon("#ddd")) == icon_pixmap("pause", 48, QColor("#ddd")).toImage()
