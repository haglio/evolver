from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from functools import partial

from app_support import production_update
from app_support.loading_screen import AppWindow, meeting_place
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
from shared_ui.colors import family_palette
from shared_ui.loading_window import Loading, LoadingCanceled

import config
from gui import branch_session, peer_watch, process_identity, single_instance
from gui.background import BackgroundQueue
from gui.log_window import RunLogWindow
from gui.main_window import EvolverMainWindow
from gui.one_window import OneWindow
from gui.presence_throttle import PresenceThrottle
from gui.queue_controller import QueueController
from gui.run_controller import RunController
from gui.run_history import RunHistory
from gui.run_record import RunRecord, format_run_label
from gui.scheduler import PipelineScheduler
from gui.settings import EvolverSettings
from gui.settings_dialog import SettingsDialog
from gui.sign_in_notice import SignInNotice
from gui.single_instance import InstanceGateway, Outcome
from gui.stats_window import StatsWindow
from gui.tray import EvolverTray
from util import crash_log, run_log
from util.alert import show_error

log = logging.getLogger(__name__)

_UPDATE_CHECK_MS = 60_000

_SHOW_WINDOW = "--show-window"
_ANY_PROCESS = -1
STEPS = (("Loading Evolver...", 1.0),)


def open_the_loading_screen():
    from shared_ui.loading_process import LoadingProcess  # noqa: PLC0415

    return LoadingProcess.open(
        caption="Evolver Loading", wordmark="Evolver", icon=process_identity.LETTER, preview=branch_session.shown_as(),
        steps=STEPS, cancel_hint="Press Esc to cancel opening Evolver",
        app_id=process_identity.identity(), taskbar=process_identity.taskbar_app())


def _say_the_running_evolver_did_not_answer(app: QApplication) -> None:
    process_identity.claim(app)
    show_error(
        "Evolver",
        "Evolver is already running but did not respond, so its window "
        "could not be opened.\n\nQuit it from the tray icon, or end the "
        "pythonw.exe process, then start Evolver again.",
    )


def _unmarked_note(record, log_path) -> str:
    if record.log_start is None:
        return ("This run predates Evolver marking its runs in the log, so "
                "there is no mark to find its lines by.")
    return (f"{log_path} no longer holds this run's lines: the file has been "
            "replaced or trimmed since the run wrote them.")


def _wire(view, slots: dict) -> None:
    offered = view.commands()
    if set(offered) != set(slots):
        raise ValueError(
            f"{type(view).__name__} offers commands {sorted(offered)}, "
            f"wired to {sorted(slots)}"
        )
    for key, signal in offered.items():
        signal.connect(slots[key])


class EvolverApp:

    def __init__(self, app: QApplication):
        self._app = app
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationName("Evolver")
        app.setPalette(family_palette(app.palette()))

        self._checkout = config.PROJECT_DIR
        self._settings = EvolverSettings.load()
        self._stats = OneWindow()
        self._background = BackgroundQueue()
        self._log_window: RunLogWindow | None = None
        self._instance = InstanceGateway()
        self._session = branch_session.BranchSession(
            self._instance, a_run_is_going=lambda: self._runs.is_running)
        self._session.leaving.connect(self._shutdown)
        self._sign_in_notice = SignInNotice()

        self._presence = PresenceThrottle(
            lambda: self._settings.nonai_upscale_enabled)

        self._peer = peer_watch.watch_the_broker()
        self._peer_timer = QTimer()
        self._peer_timer.setInterval(peer_watch.PEER_CHECK_INTERVAL_MS)
        self._peer_timer.timeout.connect(self._peer.tick)

        self._scheduler = PipelineScheduler(interval_minutes=self._settings.interval_minutes)

        self._window = EvolverMainWindow()
        self._window.setWindowTitle(self._session.name)
        self._window.set_nonai_enabled(self._settings.nonai_upscale_enabled)
        self._window.log_requested.connect(self._show_run_log)

        self._tray = EvolverTray(self._session.name, shown_as=branch_session.shown_as())
        self._tray.set_nonai_enabled(self._settings.nonai_upscale_enabled)
        self._scheduler.status_changed.connect(self._tray.show_schedule)
        self._scheduler.status_changed.connect(self._window.show_schedule)

        self._runs = RunController(
            self._window, lambda: self._settings.nonai_upscale_enabled)
        self._scheduler.run_requested.connect(self._runs.start)
        self._runs.run_started.connect(self._scheduler.mark_running)
        self._runs.run_finished.connect(self._on_finished)
        self._runs.run_failed.connect(self._on_error)
        self._runs.run_overran.connect(self._on_overrun)

        self._queue = QueueController(self._window, self._background)
        self._queue.run_wanted.connect(self._runs.start_when_free)
        self._queue.presence_poll_wanted.connect(self._presence.poll)
        self._runs.run_ended.connect(self._scheduler.mark_idle)
        self._runs.run_ended.connect(self._window.refresh_history)
        self._runs.run_ended.connect(self._queue.refresh)

        shared_commands = {
            "run_now": self._scheduler.run_now,
            "pause": self._scheduler.toggle_pause,
            "nonai": self._set_nonai_enabled,
            "settings": self._show_settings,
            "stats": self._show_stats,
            "queue": self._queue.show,
            "backfill": partial(self._launch_tool, "backfill_app.py"),
            "review_trash": partial(self._launch_tool, "review_trash_app.py"),
            "restart": self._restart,
        }
        _wire(self._tray, {**shared_commands,
                           "open": self._show_window, "quit": self._session.quit})
        _wire(self._window, {**shared_commands, "quit": self._confirm_quit})

        self._app.commitDataRequest.connect(self._on_session_end)

        self._updates = production_update.UpdateWatch(
            self._checkout, a_good_moment=self._a_good_moment_for_an_update,
            start_again=self._restart, logger=log)
        self._update_timer = QTimer()
        self._update_timer.setInterval(_UPDATE_CHECK_MS)
        self._update_timer.timeout.connect(lambda: self._updates.tick())

    def _a_good_moment_for_an_update(self) -> bool:
        on_screen = (self._window.isVisible(), self._stats.is_on_screen, self._queue.is_on_screen,
                     self._log_window is not None and self._log_window.isVisible())
        return not self._session.is_preview and not self._runs.is_running and not any(on_screen)

    def start(self) -> None:
        process_identity.claim(self._app)
        self._window.refresh_history()
        self._tray.show()
        self._keep_the_schedule()
        self._session.take_the_work()
        self._window.setWindowTitle(self._session.title(datetime.now().astimezone()))
        if _SHOW_WINDOW in sys.argv:
            self._show_window()

    def _keep_the_schedule(self) -> None:
        peer_watch.clear_evolver_stand_down()
        self._presence.start()
        self._scheduler.start()
        self._peer_timer.start()
        self._update_timer.start()
        self._peer.tick()

    def run(self) -> int:
        outcome = self._instance.become_evolver(
            as_preview=self._session.is_preview,
            only_if_not_running=single_instance.IF_NOT_RUNNING in sys.argv)
        if outcome is Outcome.UNANSWERED:
            _say_the_running_evolver_did_not_answer(self._app)
        if outcome is not Outcome.CLAIMED:
            return 0
        if (next_launch := meeting_place(os.environ)) is not None:
            next_launch.say_where_the_app_comes_up(AppWindow(size=(self._window.width(), self._window.height())))
        loading = Loading.at_the_click(self._app, log, open_the_loading_screen)
        try:
            for step, _weight in STEPS:
                loading.say(step)
        except LoadingCanceled:
            return 0

        self._instance.serve_launches(steps_aside_for=self._session.steps_aside_for,
                                      on_show=self._show_window,
                                      on_step_aside=self._session.step_aside)
        self.start()
        loading.done()
        return self._app.exec()

    def _show_window(self):
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _set_nonai_enabled(self, enabled: bool):
        self._settings.nonai_upscale_enabled = enabled
        self._settings.save()
        self._tray.set_nonai_enabled(enabled)
        self._window.set_nonai_enabled(enabled)

    def _show_settings(self):
        dialog = SettingsDialog(self._settings, self._window)
        if dialog.exec():
            self._settings = dialog.settings
            self._scheduler.set_interval_minutes(self._settings.interval_minutes)

    def _show_stats(self):
        window = self._stats.show(partial(StatsWindow, self._window))
        if window is not None:
            self._background.run(partial(RunHistory.read, config.RUNS_DIR),
                                 then=partial(self._chart_history, window))

    def _chart_history(self, window: StatsWindow, history: RunHistory):
        if window is self._stats.current:
            window.show_history(history)

    def _show_run_log(self, record: RunRecord):
        if self._log_window is not None:
            self._log_window.close()
            self._log_window.deleteLater()
        log_path = config.LOG_FILE
        text = run_log.read_run(
            log_path, record.id, record.log_start, record.log_end)
        note = "" if text is not None else _unmarked_note(record, log_path)
        self._log_window = RunLogWindow(
            format_run_label(record.started_at, record.duration_seconds),
            text or "", note, self._window,
        )
        self._log_window.show()
        self._log_window.raise_()
        self._log_window.activateWindow()

    def _launch_tool(self, script: str):
        subprocess.Popen(
            [sys.executable, str(self._checkout / script)],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )

    def _notify(self, body: str, icon: QSystemTrayIcon.MessageIcon, msecs: int):
        if not self._settings.enable_toasts:
            return
        self._tray.showMessage("Evolver", body, icon, msecs)

    def _on_finished(self, record):
        succeeded = record.status == "success"
        status = "completed" if succeeded else "completed with errors"
        self._notify(
            f"Pipeline {status} in {record.duration_seconds:.0f}s",
            QSystemTrayIcon.MessageIcon.Information if succeeded
            else QSystemTrayIcon.MessageIcon.Warning,
            5000,
        )
        self._sign_in_notice.after_run(record, time.monotonic())

    def _on_error(self, message: str):
        self._notify(f"Pipeline error: {message}",
                     QSystemTrayIcon.MessageIcon.Critical, 8000)

    def _on_overrun(self):
        self._notify(
            f"Pipeline still running past the {config.PIPELINE_WALL_TIMEOUT_SECONDS // 60}-minute "
            "limit; stopping after the current stage. New runs wait until it exits.",
            QSystemTrayIcon.MessageIcon.Critical,
            8000,
        )

    def _on_session_end(self, manager):
        crash_log.write_info(
            "Windows session end requested:",
            f"allowsInteraction={manager.allowsInteraction()}\n",
        )
        self._shutdown()

    def _confirm_quit(self):
        result = QMessageBox.question(
            self._window,
            "Quit Evolver",
            self._session.quit_question(),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            self._session.quit()

    def _restart(self):
        showing = self._window.isVisible()
        launcher = self._session.restart_launcher(showing=showing)
        production_update.start_again_after(os.getpid(), self._checkout / launcher)
        if showing:
            ctypes.windll.user32.AllowSetForegroundWindow(_ANY_PROCESS)
        self._shutdown()

    def _shutdown(self):
        self._instance.stop_serving()
        self._background.stop()
        self._runs.wait_for_exit(5000)
        self._scheduler.stop()
        self._peer_timer.stop()
        self._update_timer.stop()
        self._tray.hide()
        self._app.quit()
