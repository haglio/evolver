"""Tests for the tray's schedule display — the app's primary surface.

The window is normally hidden in the tray, so the tooltip and the
status line at the top of the tray menu are what the user actually reads;
they show the same schedule (Running / Paused / Next run) the window's
toolbar shows, off the one status the scheduler hands both.
"""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QSystemTrayIcon
from shared_ui.chrome import menu_rules
from shared_ui.colors import BG_TERTIARY, TEXT_PRIMARY, TOGGLE_OFF, TOGGLE_ON
from shared_ui.toggle_switch import ToggleSwitch

from gui.schedule_state import ScheduleStatus
from gui.switches import MenuWithSwitches
from gui.tray import EvolverTray
from tests.gui_support import QAPP


class TestTrayMenu:
    def test_the_upscale_queue_is_on_the_menu_as_it_is_on_the_toolbar(self):
        """Both surfaces carry it, so the one that is to hand is the one used
        -- the tray while the window is closed, the toolbar while it is open."""
        tray = EvolverTray()
        assert "queue" in tray.commands()
        assert tray.queue_action.text() == "Upscale Queue..."

    def test_the_three_tools_sit_together_with_a_line_above_and_below(self):
        tray = EvolverTray()
        entries = ["---" if action.isSeparator() else action.text()
                   for action in tray.contextMenu().actions()]
        first = entries.index("Upscale Queue...")

        assert entries[first - 1:first + 4] == [
            "---", "Upscale Queue...", "Backfill Metadata...", "Review Weird...", "---"]
        assert tray.commands()["review_weird"] == tray.review_weird_action.triggered


def _row_as_drawn(menu, action):
    menu.popup(QPoint(0, 0))
    try:
        QAPP.processEvents()
        return menu.grab().toImage().copy(menu.actionGeometry(action))
    finally:
        menu.hide()


def _the_upscale_non_ai_row(tray):
    return _row_as_drawn(tray.contextMenu(), tray.nonai_action)


def _columns_wearing(row, color) -> list[int]:
    return [x for x in range(row.width()) for y in range(row.height())
            if row.pixelColor(x, y).name() == color.name()]


def _pixels_in_the_upscale_non_ai_row(tray, color) -> int:
    return len(_columns_wearing(_the_upscale_non_ai_row(tray), color))


class TestUpscaleNonAiWearsASwitch:

    def test_its_switch_shows_on_in_the_menu_while_the_opt_in_is_on(self):
        tray = EvolverTray()
        tray.set_nonai_enabled(True)
        assert _pixels_in_the_upscale_non_ai_row(tray, TOGGLE_ON) > 30

    def test_its_switch_shows_off_in_the_menu_while_the_opt_in_is_off(self):
        tray = EvolverTray()
        assert _pixels_in_the_upscale_non_ai_row(tray, TOGGLE_OFF) > 30

    def test_the_menu_opens_as_wide_the_second_time_as_the_first(self):
        tray = EvolverTray()
        menu = tray.contextMenu()
        widths = []
        for _opening in range(2):
            menu.popup(QPoint(0, 0))
            QAPP.processEvents()
            widths.append(menu.width())
            menu.hide()
        assert widths[0] == widths[1]

    def test_its_switch_wears_no_ring_on_the_row_under_the_pointer(self):
        tray = EvolverTray()
        tray.set_nonai_enabled(True)
        menu = tray.contextMenu()
        menu.popup(QPoint(0, 0))
        try:
            menu.setActiveAction(tray.nonai_action)
            QAPP.processEvents()
            row = menu.grab().toImage().copy(menu.actionGeometry(tray.nonai_action))
        finally:
            menu.hide()
        assert _columns_wearing(row, BG_TERTIARY) == []

    def test_a_switch_on_the_widest_row_still_sits_clear_of_its_name(self):
        menu = MenuWithSwitches()
        menu.setStyleSheet(menu_rules())
        menu.addAction(QAction("Short", menu))
        longest = QAction("A row running longer than any other in its menu", menu)
        menu.addAction(longest)
        switch = ToggleSwitch()
        switch.setChecked(True)
        menu.put_switch_on(longest, switch)

        row = _row_as_drawn(menu, longest)
        name_ends = (min(_columns_wearing(row, TEXT_PRIMARY))
                     + menu.fontMetrics().horizontalAdvance(longest.text()))
        assert name_ends < min(_columns_wearing(row, TOGGLE_ON))


def _status_lines(tray) -> list[str]:
    lines = []
    for action in tray.contextMenu().actions():
        if action.isSeparator():
            return lines
        if action.isVisible():
            lines.append(action.text())
    return lines


class TestTrayScheduleDisplay:

    def test_a_scheduled_next_run_is_in_the_tooltip_and_the_menus_one_status_line(self):
        tray = EvolverTray()
        tray.show_schedule(ScheduleStatus(next_run_at=datetime(2026, 3, 29, 14, 30)))
        assert "Next run: 14:30" in tray.toolTip()
        assert _status_lines(tray) == ["Status: Scheduled for 14:30"]

    def test_pausing_reads_paused_with_no_time(self):
        tray = EvolverTray()
        tray.show_schedule(ScheduleStatus(is_paused=True))
        assert "Paused" in tray.toolTip()
        assert _status_lines(tray) == ["Status: Paused"]

    def test_pausing_turns_the_menu_item_into_resume(self):
        tray = EvolverTray()
        tray.show_schedule(ScheduleStatus(is_paused=True))
        assert tray.pause_action.text() == "Resume Scheduling"
        tray.show_schedule(ScheduleStatus())
        assert tray.pause_action.text() == "Pause Scheduling"

    def test_a_running_pipeline_reads_running_and_disables_run_now(self):
        tray = EvolverTray()
        tray.show_schedule(ScheduleStatus(
            is_running=True, next_run_at=datetime(2026, 3, 29, 14, 30)))
        assert "Running..." in tray.toolTip()
        assert _status_lines(tray) == ["Status: Running"]
        assert not tray.run_now_action.isEnabled()

    def test_a_finished_run_reenables_run_now(self):
        tray = EvolverTray()
        tray.show_schedule(ScheduleStatus(is_running=True))
        tray.show_schedule(ScheduleStatus())
        assert tray.run_now_action.isEnabled()

    def test_running_outranks_paused_in_the_tray(self):
        """A run on screen is the fact the user is looking at; the pause stops
        the schedule after it.  The window reads it the same way, off the same
        status (bug 48)."""
        tray = EvolverTray()
        tray.show_schedule(ScheduleStatus(is_running=True, is_paused=True))
        assert "Running..." in tray.toolTip()
        assert tray._status_action.text() == "Status: Running"

    def test_with_nothing_scheduled_the_tooltip_is_just_the_name(self):
        tray = EvolverTray()
        assert tray.toolTip() == "Evolver"

    def test_double_clicking_the_icon_opens_the_window(self):
        tray = EvolverTray()
        opened = []
        tray.open_action.triggered.connect(lambda *_: opened.append(True))
        tray._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        assert opened == [True]

    def test_a_single_click_does_not_open_the_window(self):
        tray = EvolverTray()
        opened = []
        tray.open_action.triggered.connect(lambda *_: opened.append(True))
        tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
        assert opened == []
