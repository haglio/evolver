"""Top-level application wiring: tray, window, scheduler, worker."""

from __future__ import annotations

import ctypes
import logging
import sys

from PyQt6.QtWidgets import QApplication

from gui.main_window import EvolverMainWindow
from gui.scheduler import PipelineScheduler
from gui.settings import EvolverSettings
from gui.settings_dialog import SettingsDialog
from gui.tray import EvolverTray
from gui.worker import PipelineWorker

log = logging.getLogger(__name__)

_MUTEX_NAME = "EvolverTrayApp_SingleInstance"


_CreateMutexW = ctypes.windll.kernel32.CreateMutexW
_CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
_CreateMutexW.restype = ctypes.c_void_p

_GetLastError = ctypes.windll.kernel32.GetLastError
_GetLastError.argtypes = []
_GetLastError.restype = ctypes.c_ulong


def _acquire_single_instance_mutex() -> bool:
    """Try to acquire a named mutex. Returns True if this is the first instance."""
    _ERROR_ALREADY_EXISTS = 183
    handle = _CreateMutexW(None, False, _MUTEX_NAME)
    if not handle:
        return True  # CreateMutex failed entirely; proceed anyway
    return _GetLastError() != _ERROR_ALREADY_EXISTS


class EvolverApp:
    """Wires together all GUI components and runs the Qt event loop."""

    def __init__(self):
        self._app = QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationName("Evolver")

        self._settings = EvolverSettings.load()
        self._worker: PipelineWorker | None = None

        self._scheduler = PipelineScheduler(interval_minutes=self._settings.interval_minutes)
        self._scheduler.run_requested.connect(self._start_run)
        self._scheduler.status_changed.connect(self._update_status_display)

        self._tray = EvolverTray()
        self._app.setWindowIcon(self._tray.icon())
        self._tray.open_action.triggered.connect(self._show_window)
        self._tray.run_now_action.triggered.connect(self._scheduler.run_now)
        self._tray.pause_action.triggered.connect(self._toggle_pause)
        self._tray.settings_action.triggered.connect(self._show_settings)
        self._tray.quit_action.triggered.connect(self._quit)

        self._window = EvolverMainWindow()
        self._window.run_now_action.triggered.connect(self._scheduler.run_now)
        self._window.active_toggle.triggered.connect(self._toggle_pause)
        self._window.settings_action.triggered.connect(self._show_settings)
        self._window.quit_action.triggered.connect(self._quit)
        self._window.refresh_history()

    def run(self) -> int:
        if not _acquire_single_instance_mutex():
            self._tray.showMessage("Evolver", "Already running.", self._tray.MessageIcon.Information, 3000)
            return 0

        self._tray.show()
        self._scheduler.start()
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

    def _show_settings(self):
        dialog = SettingsDialog(self._settings, self._window)
        if dialog.exec():
            self._settings = dialog.settings
            self._scheduler.set_interval_minutes(self._settings.interval_minutes)

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

        self._worker = PipelineWorker(trigger=trigger)
        self._worker.stage_started.connect(self._window.progress_widget.on_stage_started)
        self._worker.stage_completed.connect(self._window.progress_widget.on_stage_completed)
        self._worker.pipeline_finished.connect(self._on_finished)
        self._worker.pipeline_error.connect(self._on_error)

        self._window.show_progress()
        self._worker.start()

    def _on_finished(self, record):
        self._scheduler.mark_idle()
        self._tray.set_running(False)
        self._window.finish_progress()
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
        self._scheduler.mark_idle()
        self._tray.set_running(False)
        self._window.finish_progress()
        self._window.refresh_history()

        if self._settings.enable_toasts:
            self._tray.showMessage("Evolver", f"Pipeline error: {message}", self._tray.MessageIcon.Critical, 8000)
        log.error("Pipeline error: %s", message)

    def _quit(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(5000)
        self._scheduler.stop()
        self._tray.hide()
        self._app.quit()
