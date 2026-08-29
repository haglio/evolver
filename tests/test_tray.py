"""Tests for the tray's schedule display — the app's primary surface.

The window is normally hidden in the tray, so the tooltip and the two
status lines at the top of the tray menu are what the user actually reads;
they decide the same three-state display (Running / Paused / Next run)
that EvolverMainWindow.update_schedule_status decides, and until now only
the window half was tested.
"""

from datetime import datetime

from PyQt6.QtWidgets import QSystemTrayIcon

from gui.tray import EvolverTray


class TestTrayScheduleDisplay:

    def test_a_scheduled_next_run_is_in_the_tooltip_and_the_menu(self):
        tray = EvolverTray()
        tray.set_next_run_at(datetime(2026, 3, 29, 14, 30))
        assert "Next run: 14:30" in tray.toolTip()
        assert tray._status_action.text() == "Status: Scheduled"
        assert tray._next_run_action.isVisible()
        assert "14:30" in tray._next_run_action.text()

    def test_pausing_reads_paused_and_hides_the_next_run(self):
        tray = EvolverTray()
        tray.set_next_run_at(datetime(2026, 3, 29, 14, 30))
        tray.set_paused(True)
        assert "Paused" in tray.toolTip()
        assert tray._status_action.text() == "Status: Paused"
        assert not tray._next_run_action.isVisible()

    def test_pausing_turns_the_menu_item_into_resume(self):
        tray = EvolverTray()
        tray.set_paused(True)
        assert tray.pause_action.text() == "Resume Scheduling"
        tray.set_paused(False)
        assert tray.pause_action.text() == "Pause Scheduling"

    def test_a_running_pipeline_reads_running_and_disables_run_now(self):
        tray = EvolverTray()
        tray.set_next_run_at(datetime(2026, 3, 29, 14, 30))
        tray.set_running(True)
        assert "Running..." in tray.toolTip()
        assert tray._status_action.text() == "Status: Running"
        assert not tray.run_now_action.isEnabled()
        assert not tray._next_run_action.isVisible()

    def test_a_finished_run_reenables_run_now(self):
        tray = EvolverTray()
        tray.set_running(True)
        tray.set_running(False)
        assert tray.run_now_action.isEnabled()

    def test_running_outranks_paused_in_the_tray(self):
        """Pinned as it behaves today. The window decides the same state the
        other way around (paused before running), so pausing mid-run shows
        "Running" here and "inactive" there -- recorded as a divergence in the
        changelog, not resolved by this test.
        """
        tray = EvolverTray()
        tray.set_paused(True)
        tray.set_running(True)
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
