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

    def test_it_is_the_familys_restart_mark_the_power_marks_relative_since_a_redo_arrow_reads_as_undo(self):
        assert _drawn_exactly_as_shared_ui_draws(restart_icon("#ddd"), "restart")

    def test_it_takes_the_ink_the_chrome_it_sits_on_needs(self):
        assert _rendered(restart_icon("#ddd")) != _rendered(restart_icon("#333"))
        assert _drawn_exactly_as_shared_ui_draws(restart_icon("#333"), "restart", "#333")


class TestQuitIcon:

    def test_it_is_the_power_mark_fun_time_paints_on_its_bar_beside_it(self):
        assert _drawn_exactly_as_shared_ui_draws(quit_icon("#ddd"), "power")


class TestRunNowIcon:

    def test_it_is_the_familys_play_triangle(self):
        assert _drawn_exactly_as_shared_ui_draws(run_now_icon("#ddd"), "play")


class TestPauseIcon:

    def test_it_is_the_pause_bars_the_brokers_tray_menu_pauses_with_beside_it(self):
        assert _drawn_exactly_as_shared_ui_draws(pause_icon("#ddd"), "pause")


class TestReviewTrashIcon:

    def test_it_is_the_trash_can_the_funestras_send_to_trash_button_wears(self):
        assert _drawn_exactly_as_shared_ui_draws(review_trash_icon("#ddd"), "trash")
