"""Top-level application wiring: tray, window, scheduler, worker."""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalServer
from PyQt6.QtWidgets import QApplication, QMessageBox

import config
from gui import process_identity, single_instance
from gui.main_window import EvolverMainWindow
from gui.progress_popup import ProgressPopup
from gui.run_record import load_runs
from gui.scheduler import PipelineScheduler
from gui.settings import EvolverSettings
from gui.settings_dialog import SettingsDialog
from gui.stats_window import StatsWindow
from gui.tray import EvolverTray
from gui.worker import PipelineWorker
from tasks import nonai_upscale
from util import crash_log
from util.windows_alert import show_error_window

log = logging.getLogger(__name__)


class EvolverApp:
    """Wires together all GUI components and runs the Qt event loop.

    Split in two on purpose. ``__init__`` only *builds*: it constructs the
    parts and connects them, and touches nothing outside the process. ``start``
    is everything the app *does* -- claim the Windows identity, read the run
    history off disk, start the two timers, show the tray. Merely constructing
    one used to name this process to the shell and begin a twenty-second
    presence poll, which is why every test of any one part had to build the
    whole thing and then live with a running timer for the rest of the session.
    """

    def __init__(self):
        self._app = QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationName("Evolver")

        self._settings = EvolverSettings.load()
        self._worker: PipelineWorker | None = None
        self._stats_window: StatsWindow | None = None
        self._progress_popup: ProgressPopup | None = None
        self._show_requests: QLocalServer | None = None

        self._watchdog = QTimer()
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._on_watchdog)

        # Presence poll: parks/thaws the in-flight non-AI encode between the
        # slow pipeline ticks, so returning to the machine suspends it in
        # seconds. The handler no-ops unless the toggle is on.
        self._presence_monitor = QTimer()
        self._presence_monitor.setInterval(int(config.NONAI_PRESENCE_POLL_SECONDS * 1000))
        self._presence_monitor.timeout.connect(self._throttle_presence)

        self._scheduler = PipelineScheduler(interval_minutes=self._settings.interval_minutes)
        self._scheduler.run_requested.connect(self._start_run)
        self._scheduler.status_changed.connect(self._update_status_display)

        self._tray = EvolverTray()
        self._app.setWindowIcon(self._tray.icon())
        self._tray.open_action.triggered.connect(self._show_window)
        self._tray.run_now_action.triggered.connect(self._scheduler.run_now)
        self._tray.pause_action.triggered.connect(self._toggle_pause)
        self._tray.nonai_action.setChecked(self._settings.nonai_upscale_enabled)
        self._tray.nonai_action.toggled.connect(self._set_nonai_enabled)
        self._tray.settings_action.triggered.connect(self._show_settings)
        self._tray.stats_action.triggered.connect(self._show_stats)
        self._tray.backfill_action.triggered.connect(self._launch_backfill)
        self._tray.restart_action.triggered.connect(self._restart)
        self._tray.quit_action.triggered.connect(self._quit)

        self._app.commitDataRequest.connect(self._on_session_end)

        self._window = EvolverMainWindow()
        self._window.run_now_action.triggered.connect(self._scheduler.run_now)
        self._window.active_toggle.clicked.connect(self._toggle_pause)
        self._window.settings_action.triggered.connect(self._show_settings)
        self._window.stats_action.triggered.connect(self._show_stats)
        self._window.restart_action.triggered.connect(self._restart)
        self._window.quit_action.triggered.connect(self._confirm_quit)

    def start(self) -> None:
        """Everything the app does to the machine, in the order it must happen.

        The identity goes first: the taskbar reads it when a window of this
        process first appears, so claiming it after the tray is up is claiming
        it too late.
        """
        process_identity.claim(int(self._window.winId()))
        self._window.refresh_history()
        self._presence_monitor.start()
        self._tray.show()
        self._scheduler.start()
        if "--show-window" in sys.argv:
            self._show_window()

    def run(self) -> int:
        if not single_instance.is_first_instance():
            crash_log.write_info(
                "Already running:", "duplicate launch handed to the running instance\n",
            )
            if not single_instance.request_show():
                show_error_window(
                    "Evolver",
                    "Evolver is already running but did not respond, so its window "
                    "could not be opened.\n\nQuit it from the tray icon, or end the "
                    "pythonw.exe process, then start Evolver again.",
                )
            return 0

        # Held for the process's life: if this is collected the pipe closes with
        # it, and every later launch fails the handoff instead of taking it.
        self._show_requests = single_instance.serve_show_requests(self._show_window)

        self.start()
        return self._app.exec()

    def _show_window(self):
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _toggle_pause(self):
        if self._scheduler.is_paused:
            self._scheduler.resume()
            self._tray.set_paused(False)
        else:
            self._scheduler.pause()
            self._tray.set_paused(True)

    def _set_nonai_enabled(self, enabled: bool):
        """Persist the one-time opt-in; presence polling and the next tick act on it."""
        self._settings.nonai_upscale_enabled = enabled
        self._settings.save()

    def _throttle_presence(self):
        """Suspend/resume the in-flight non-AI encode as the user comes and goes.

        Fires far more often than the pipeline tick, so returning to the machine
        freezes the encode within seconds. No-op unless the user has opted in.
        """
        if not self._settings.nonai_upscale_enabled:
            return
        nonai_upscale.throttle_to_presence()

    def _show_settings(self):
        dialog = SettingsDialog(self._settings, self._window)
        if dialog.exec():
            self._settings = dialog.settings
            self._scheduler.set_interval_minutes(self._settings.interval_minutes)

    def _show_stats(self):
        if self._stats_window is not None and self._stats_window.isVisible():
            self._stats_window.raise_()
            self._stats_window.activateWindow()
            return
        records = load_runs(config.RUNS_DIR)
        self._stats_window = StatsWindow(records, self._window)
        self._stats_window.show()

    def _launch_backfill(self):
        """Start the metadata backfill tool as its own process.

        Detached rather than in-process: it holds the microphone open and drives a
        media backend for as long as the user keeps labelling, and neither belongs
        in the tray process that has to survive the whole session.
        """
        subprocess.Popen(
            [sys.executable, str(config.PROJECT_DIR / "backfill_app.py")],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    def _update_status_display(self):
        """Push scheduling state to tray and window."""
        self._tray.set_next_run_at(self._scheduler.next_run_at)
        self._window.update_schedule_status(
            self._scheduler.is_running,
            self._scheduler.is_paused,
            self._scheduler.next_run_at,
        )

    def _start_run(self, trigger: str):
        if self._worker is not None and self._worker.isRunning():
            return

        self._scheduler.mark_running()
        self._tray.set_running(True)

        self._worker = PipelineWorker(
            trigger=trigger, nonai_enabled=self._settings.nonai_upscale_enabled,
        )
        self._worker.pipeline_finished.connect(self._on_finished)
        self._worker.pipeline_error.connect(self._on_error)

        if self._window.isVisible():
            self._progress_popup = ProgressPopup(parent=self._window)
            self._worker.stage_started.connect(self._progress_popup.on_stage_started)
            self._worker.stage_completed.connect(self._progress_popup.on_stage_completed)
            self._worker.stage_progress.connect(self._progress_popup.on_stage_progress)
            self._progress_popup.show_over(self._window)

        self._worker.start()
        self._watchdog.start(config.PIPELINE_WALL_TIMEOUT_SECONDS * 1000)

    def _on_finished(self, record):
        self._watchdog.stop()
        self._scheduler.mark_idle()
        self._tray.set_running(False)
        if self._progress_popup is not None:
            self._progress_popup.on_pipeline_finished()
        self._window.refresh_history()

        if self._settings.enable_toasts:
            status = "completed" if record.status == "success" else "completed with errors"
            self._tray.showMessage(
                "Evolver",
                f"Pipeline {status} in {record.duration_seconds:.0f}s",
                self._tray.MessageIcon.Information if record.status == "success" else self._tray.MessageIcon.Warning,
                5000,
            )

    def _on_error(self, message: str):
        self._watchdog.stop()
        self._scheduler.mark_idle()
        self._tray.set_running(False)
        if self._progress_popup is not None:
            self._progress_popup.on_pipeline_finished()
        self._window.refresh_history()

        if self._settings.enable_toasts:
            self._tray.showMessage("Evolver", f"Pipeline error: {message}", self._tray.MessageIcon.Critical, 8000)
        log.error("Pipeline error: %s", message)

    def _on_watchdog(self):
        if self._worker is None or not self._worker.isRunning():
            return  # Run finished just before the timer fired

        log.critical(
            "Watchdog fired: pipeline exceeded %d-second wall-clock limit; "
            "asking it to stop after the current stage",
            config.PIPELINE_WALL_TIMEOUT_SECONDS,
        )

        # The run really is still going, so nothing here may pretend otherwise.
        # The worker stays referenced and its signals stay connected: it is the
        # re-entry guard in _start_run (dropping a running QThread's last
        # reference can abort the process), and its eventual finish is what
        # tears down and re-opens scheduling. The stop is cooperative —
        # run_pipeline checks between stages, so a stage mid-move finishes its
        # current file rather than being cut.
        self._worker.requestInterruption()

        if self._settings.enable_toasts:
            self._tray.showMessage(
                "Evolver",
                f"Pipeline still running past the {config.PIPELINE_WALL_TIMEOUT_SECONDS // 60}-minute "
                "limit; stopping after the current stage. New runs wait until it exits.",
                self._tray.MessageIcon.Critical,
                8000,
            )

    def _on_session_end(self, manager):
        """Handle Windows session-management events (shutdown, logoff, installer restart).

        Logs the event and initiates a graceful shutdown so the scheduler,
        worker thread, and any running subprocesses are cleaned up before
        Windows force-kills the process.
        """
        crash_log.write_info(
            "Windows session end requested:",
            f"allowsInteraction={manager.allowsInteraction()}\n",
        )
        self._quit()

    def _confirm_quit(self):
        result = QMessageBox.question(
            self._window,
            "Quit Evolver",
            "Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            self._quit()

    def _restart(self):
        cmd = [sys.executable, str(config.PROJECT_DIR / "tray_app.py")]
        show = self._window.isVisible()
        if show:
            cmd.append("--show-window")
        proc = subprocess.Popen(
            cmd,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        if show:
            ctypes.windll.user32.AllowSetForegroundWindow(proc.pid)
        self._quit()

    def _quit(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(5000)
        self._scheduler.stop()
        self._tray.hide()
        self._app.quit()
