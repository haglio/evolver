from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QIcon, QImage
from shared_ui.icons import icon_pixmap

from gui.icons import pause_icon, quit_icon, restart_icon, review_trash_icon, run_now_icon

_SIZE = QSize(48, 48)


def _rendered(icon: QIcon) -> QImage:
    return icon.pixmap(_SIZE, QIcon.Mode.Normal).toImage()


def _drawn_exactly_as_shared_ui_draws(icon: QIcon, symbol: str, ink: str = "#ddd") -> bool:
    return _rendered(icon) == icon_pixmap(symbol, _SIZE.width(), QColor(ink)).toImage()


class TestRestartIcon:

    def test_it_is_the_familys_restart_mark(self):
        assert _drawn_exactly_as_shared_ui_draws(restart_icon("#ddd"), "restart"), (
            "the power mark's relative beside Quit; a redo arrow reads as an undo")

    def test_it_takes_the_ink_the_chrome_it_sits_on_needs(self):
        assert _rendered(restart_icon("#ddd")) != _rendered(restart_icon("#333"))
        assert _drawn_exactly_as_shared_ui_draws(restart_icon("#333"), "restart", "#333")


class TestQuitIcon:

    def test_it_is_fun_times_power_mark(self):
        assert _drawn_exactly_as_shared_ui_draws(quit_icon("#ddd"), "power"), (
            "Fun Time paints this mark on its bar, and the two apps are open together")


class TestRunNowIcon:

    def test_it_is_the_familys_play_triangle(self):
        assert _drawn_exactly_as_shared_ui_draws(run_now_icon("#ddd"), "play")


class TestPauseIcon:

    def test_it_is_the_brokers_pause_mark(self):
        assert _drawn_exactly_as_shared_ui_draws(pause_icon("#ddd"), "pause"), (
            "the Broker's tray menu pauses with this mark, beside Evolver's in the tray")


class TestReviewTrashIcon:

    def test_it_is_the_funestras_trash_mark(self):
        assert _drawn_exactly_as_shared_ui_draws(review_trash_icon("#ddd"), "trash"), (
            "the Funestras' Send to Trash button wears this mark")
