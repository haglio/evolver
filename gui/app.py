"""Top-level application wiring: tray, window, scheduler, worker."""

from __future__ import annotations

import ctypes
import logging
import subprocess
import sys
import time
from datetime import datetime
from functools import partial

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

import config
import evolver
from gui import branch_session, peer_watch, process_identity, single_instance
from gui.background import BackgroundQueue
from gui.log_window import RunLogWindow
from gui.main_window import EvolverMainWindow
from gui.palette import apply_accent
from gui.presence_throttle import PresenceThrottle
from gui.queue_window import UpscaleQueueWindow
from gui.run_controller import RunController
from gui.run_record import RunRecord, format_run_label, load_runs
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

# How long a preview whose time is up waits for the run in flight to end.
_HAND_BACK_RETRY_MS = 60_000


def _unmarked_note(record, log_path) -> str:
    """Why a run's lines are not on screen, in the window's own words."""
    if record.log_start is None:
        return ("This run predates Evolver marking its runs in the log, so "
                "there is no mark to find its lines by.")
    return (f"{log_path} no longer holds this run's lines: the file has been "
            "replaced or trimmed since the run wrote them.")


def _wire(view, slots: dict) -> None:
    """Connect each of *view*'s commands to the slot of the same name.

    The two sides are held equal on purpose. A control a view offers that
    nothing is wired to is a menu item that does nothing when clicked, and a
    slot no view offers is a command the user cannot reach -- neither shows up
    anywhere else, because a QAction with no connection raises nothing. It
    fails here, while the app is being built and before it has done anything.
    """
    offered = view.commands()
    if set(offered) != set(slots):
        raise ValueError(
            f"{type(view).__name__} offers commands {sorted(offered)}, "
            f"wired to {sorted(slots)}"
        )
    for key, signal in offered.items():
        signal.connect(slots[key])


class EvolverApp:
    """Wires together all GUI components and runs the Qt event loop.

    Split in two on purpose. ``__init__`` only *builds*: it constructs the
    parts and connects them, and touches nothing outside the process. ``start``
    is everything the app *does* -- claim the Windows identity, read the run
    history off disk, start the two timers, show the tray. So constructing one
    names nothing to the shell and starts no timer, which is what lets a test
    build one part without a twenty-second presence poll running for the rest
    of the session.
    """

    def __init__(self):
        self._app = QApplication(sys.argv)
        self._app.setQuitOnLastWindowClosed(False)
        self._app.setApplicationName("Evolver")
        apply_accent(self._app)

        # Read once: what this process is was settled by the launcher that
        # started it, and every branch below has to give the same answer.
        self._branch_session = branch_session.is_one()
        self._name = branch_session.app_name()
        self._settings = EvolverSettings.load()
        self._stats_window: StatsWindow | None = None
        self._queue_window: UpscaleQueueWindow | None = None
        # The queue window's reads and verbs reach into the non-AI stage, which
        # a run can hold for as long as starting an encode takes.
        self._background = BackgroundQueue()
        self._log_window: RunLogWindow | None = None
        self._instance = InstanceGateway()
        self._sign_in_notice = SignInNotice()

        # Parks and thaws the in-flight non-AI encode between the slow pipeline
        # ticks, so returning to the machine suspends it in seconds. Reads the
        # opt-in at every poll, since the tray toggle flips it while it runs.
        self._presence = PresenceThrottle(
            lambda: self._settings.nonai_upscale_enabled)

        # The other half of the pair that keeps both apps up. Evolver starts the
        # broker's tray when it finds it gone, and that tray does the same for
        # Evolver -- which is where Evolver's own supervision comes from, since
        # the tray is revived by a scheduled task and Evolver is revived by the
        # tray. See gui/peer_watch.py.
        self._peer = peer_watch.watch_the_broker()
        self._peer_timer = QTimer()
        self._peer_timer.setInterval(peer_watch.PEER_CHECK_INTERVAL_MS)
        self._peer_timer.timeout.connect(self._peer.tick)

        self._scheduler = PipelineScheduler(interval_minutes=self._settings.interval_minutes)
        self._scheduler.status_changed.connect(self._update_status_display)

        # A preview's own end: see gui/branch_session.py.
        self._hand_back = QTimer()
        self._hand_back.setSingleShot(True)
        self._hand_back.setInterval(branch_session.HAND_BACK_AFTER_MINUTES * 60_000)
        self._hand_back.timeout.connect(self._hand_back_when_free)

        self._tray = EvolverTray(self._name)
        self._app.setWindowIcon(self._tray.icon())
        self._tray.set_nonai_enabled(self._settings.nonai_upscale_enabled)
        _wire(self._tray, {
            "open": self._show_window,
            "run_now": self._scheduler.run_now,
            "pause": self._toggle_pause,
            "nonai": self._set_nonai_enabled,
            "settings": self._show_settings,
            "stats": self._show_stats,
            "queue": self._show_queue,
            "backfill": self._launch_backfill,
            "restart": self._restart,
            "quit": self._quit_by_request,
        })

        self._app.commitDataRequest.connect(self._on_session_end)

        self._window = EvolverMainWindow()
        self._window.setWindowTitle(self._name)
        # Quit is the one command that means something different here: from the
        # window it asks first, because the window is where a stray click lands.
        _wire(self._window, {
            "run_now": self._scheduler.run_now,
            "pause": self._toggle_pause,
            "settings": self._show_settings,
            "stats": self._show_stats,
            "queue": self._show_queue,
            "restart": self._restart,
            "quit": self._confirm_quit,
        })
        # Not one of the window's commands: those are the toolbar's, named the
        # same on the tray. This one carries the run that was clicked.
        self._window.log_requested.connect(self._show_run_log)

        # The non-AI toggle is read at every start rather than held from
        # construction: the tray flips it between runs.
        self._runs = RunController(
            self._window, lambda: self._settings.nonai_upscale_enabled)
        self._scheduler.run_requested.connect(self._runs.start)
        self._runs.run_started.connect(self._on_run_started)
        self._runs.run_ended.connect(self._on_run_ended)
        self._runs.run_finished.connect(self._on_finished)
        self._runs.run_failed.connect(self._on_error)
        self._runs.run_overran.connect(self._on_overrun)

    def start(self) -> None:
        """Everything the app does to the machine, in the order it must happen.

        The identity goes first: the taskbar reads it when a window of this
        process first appears, so claiming it after the tray is up is claiming
        it too late.
        """
        process_identity.claim(int(self._window.winId()))
        self._window.refresh_history()
        self._tray.show()
        self._keep_the_schedule()
        if self._branch_session:
            self._hand_back.start()
            self._window.setWindowTitle(
                f"{self._name}, until {branch_session.until(datetime.now())}")
        if "--show-window" in sys.argv:
            self._show_window()

    def _keep_the_schedule(self) -> None:
        """Start the timers only the one running Evolver keeps: the schedule,
        the presence poll that parks the non-AI encode, and the broker watch."""
        # Whatever the user wanted the last time they closed Evolver, starting it
        # is them wanting it up now -- so the stand-down goes before the first
        # peer check, not after it.
        peer_watch.clear_evolver_stand_down()
        self._presence.start()
        self._scheduler.start()
        self._peer_timer.start()
        self._peer.tick()

    def _hand_back_when_free(self):
        """Hand the work back, unless a run is mid-stage; then try again later.

        Handing back quits, and a quit gives the stage in flight five seconds.
        """
        if self._runs.is_running:
            self._hand_back.start(_HAND_BACK_RETRY_MS)
            return
        self._hand_back_now()

    def _hand_back_now(self):
        """Give the usual Evolver its work back, and quit.

        The claim goes first, so the Evolver started next can take it at once:
        one from before launches spoke hands its launch to whoever holds the
        claim, and would open this preview's window instead. Should it fail to
        start, the broker's watch starts it, since a preview never stands
        Evolver down.
        """
        self._instance.let_go()
        branch_session.start_the_usual_evolver()
        self._shutdown()

    def run(self) -> int:
        launch = single_instance.PREVIEW if self._branch_session else single_instance.USUAL
        outcome = self._instance.take_over(launch, end_the_unanswering=self._branch_session)
        if outcome is not Outcome.CLAIMED:
            self._leave_this_launch(outcome)
            return 0

        self._instance.serve_launches(steps_aside_for=self._steps_aside_for,
                                      on_show=self._show_window,
                                      on_step_aside=self._step_aside)
        self.start()
        return self._app.exec()

    def _leave_this_launch(self, outcome: Outcome):
        """This launch went to the Evolver already running; say why if it could not.

        A wedged instance holds the mutex while answering nothing, and exiting
        into silence there looks exactly like a shortcut that does nothing.
        """
        crash_log.write_info(
            "Already running:", "duplicate launch handed to the running instance\n",
        )
        if outcome is Outcome.HANDED_OFF:
            return
        show_error(
            "Evolver",
            "Evolver is already running but did not respond, so its window "
            "could not be opened.\n\nQuit it from the tray icon, or end the "
            "pythonw.exe process, then start Evolver again.",
        )

    def _steps_aside_for(self, launch: bytes) -> bool:
        """Whether a launch that found this Evolver running takes the work from it.

        A preview always does -- that is what it was launched for -- and a
        preview makes way for the Evolver the user runs, which is how a preview
        forgotten about ends. A launcher that says nothing predates the answers
        and leaves on the connection, so for that one the window opens.
        """
        if launch == single_instance.PREVIEW:
            return True
        return self._branch_session and launch == single_instance.USUAL

    def _step_aside(self):
        """Quit for the Evolver taking the work over, without standing Evolver down."""
        crash_log.write_info("Stepping aside:", "another Evolver is taking the work over\n")
        self._shutdown()

    def _show_window(self):
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _toggle_pause(self):
        if self._scheduler.is_paused:
            self._scheduler.resume()
        else:
            self._scheduler.pause()

    def _set_nonai_enabled(self, enabled: bool):
        """Persist the one-time opt-in; presence polling and the next tick act on it."""
        self._settings.nonai_upscale_enabled = enabled
        self._settings.save()

    def _show_settings(self):
        dialog = SettingsDialog(self._settings, self._window)
        if dialog.exec():
            self._settings = dialog.settings
            self._scheduler.set_interval_minutes(self._settings.interval_minutes)

    def _show_stats(self):
        if self._stats_window is not None:
            if self._stats_window.isVisible():
                self._stats_window.raise_()
                self._stats_window.activateWindow()
                return
            # Closed, but parented to the main window, so one replaced without
            # being taken down stays alive for the process's whole life.
            self._stats_window.close()
            self._stats_window.deleteLater()
        records = load_runs(config.RUNS_DIR)
        self._stats_window = StatsWindow(records, self._window)
        self._stats_window.show()

    def _show_queue(self):
        """Open the upscale queue, or raise the one already open.

        Held like the stats window is, and for the same reason: parented to the
        main window, one replaced without being taken down would live for the
        rest of the session.
        """
        if self._queue_window is not None:
            if self._queue_window.isVisible():
                self._queue_window.raise_()
                self._queue_window.activateWindow()
                return
            self._queue_window.close()
            self._queue_window.deleteLater()
        self._queue_window = UpscaleQueueWindow(self._window)
        self._queue_window.arranged.connect(self._arrange_queue)
        self._queue_window.placed_first.connect(self._upscale_next)
        self._queue_window.now_requested.connect(self._upscale_now)
        self._queue_window.now_withdrawn.connect(self._withdraw_upscale_now)
        self._queue_window.refresh_wanted.connect(self._refresh_queue)
        self._refresh_queue()
        self._queue_window.show()

    def _arrange_queue(self, videos: list):
        """Keep the order the window was just put in — it leads the next run."""
        self._background.run(partial(evolver.arrange_upscale_queue, videos))

    def _upscale_next(self, video: str):
        """Put *video* first; it starts at the usual moment, like any other."""
        self._background.run(partial(evolver.upscale_next, video),
                             then=lambda _: self._refresh_queue())

    def _upscale_now(self, video: str):
        """Ask for *video* now, and bring the run that starts it forward.

        Encodes start on a pipeline run and nowhere else, so without this the
        video asked for would wait out the rest of the ten-minute interval.
        """
        self._background.run(partial(evolver.upscale_now, video),
                             then=self._start_what_was_asked_for)

    def _start_what_was_asked_for(self, _):
        self._refresh_queue()
        self._runs.start_when_free("manual")

    def _withdraw_upscale_now(self):
        """Stop asking for the video on the first row, and park it if you're here.

        The poll that parks an encode for the user's presence runs every twenty
        seconds; polling as soon as the ask is gone is what makes the click take
        effect while they are looking at it.
        """
        self._background.run(evolver.withdraw_upscale_now, then=self._park_if_present)

    def _park_if_present(self, _):
        self._presence.poll()
        self._refresh_queue()

    def _refresh_queue(self):
        if self._queue_window is not None:
            self._background.run(evolver.upscale_lineup, then=self._draw_queue)

    def _draw_queue(self, lineup):
        if self._queue_window is not None:
            self._queue_window.show_lineup(lineup)

    def _show_run_log(self, record: RunRecord):
        """Open the log where this run wrote, rather than at its top.

        Rebuilt each time rather than raised like the stats window: a different
        run is different content, and the one before it is closed and dropped
        so a window per click cannot pile up under the main one.
        """
        if self._log_window is not None:
            self._log_window.close()
            self._log_window.deleteLater()
        # Read once and handed on: the reader takes the path, so it does not
        # have to reach for the ambient config itself.
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

    def _update_status_display(self, status):
        """Push scheduling state to tray and window."""
        self._tray.show_schedule(status)
        self._window.show_schedule(status)

    def _on_run_started(self):
        self._scheduler.mark_running()

    def _on_run_ended(self):
        self._scheduler.mark_idle()
        self._window.refresh_history()
        # A run is what starts, promotes and fails encodes, so the queue on
        # screen is a run old the moment one ends.
        self._refresh_queue()

    def _notify(self, body: str, icon: QSystemTrayIcon.MessageIcon, msecs: int):
        """Say something in a tray balloon, if the user asked for balloons."""
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
        """An overrun is news and nothing else: the run really is still going.

        No mark_idle and no set_running(False) -- either would re-enable Run
        Now and let the scheduler tick into a run that cannot start.
        """
        self._notify(
            f"Pipeline still running past the {config.PIPELINE_WALL_TIMEOUT_SECONDS // 60}-minute "
            "limit; stopping after the current stage. New runs wait until it exits.",
            QSystemTrayIcon.MessageIcon.Critical,
            8000,
        )

    def _on_session_end(self, manager):
        """Handle Windows session-management events (shutdown, logoff, installer restart).

        Logs the event, then quits the way the tray menu does: the scheduler
        stops and the worker thread is given five seconds to finish its stage.
        What it deliberately does NOT do is touch the detached processes -- the
        in-flight non-AI encode, the backfill tool -- because those are
        detached precisely so they outlive this one, and Windows is about to
        end the session for all of them anyway.
        """
        crash_log.write_info(
            "Windows session end requested:",
            f"allowsInteraction={manager.allowsInteraction()}\n",
        )
        self._shutdown()

    def _confirm_quit(self):
        result = QMessageBox.question(
            self._window,
            "Quit Evolver",
            "Quit this preview? Your usual Evolver takes the work back."
            if self._branch_session else "Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            self._quit_by_request()

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
        self._shutdown()

    def _quit_by_request(self):
        """Quit because the user asked for it — the one quit the broker honors.

        Every other way Evolver goes down leaves no mark and is undone within the
        quarter hour: a crash, a kill from the task list, the quit above that
        Windows asks for when it announces a session end and then, sometimes,
        cancels. This one leaves a mark, so closing Evolver on purpose is not
        argued with. Starting it again clears the mark; see start().
        """
        if self._branch_session:
            self._hand_back_now()
            return
        peer_watch.stand_evolver_down()
        self._shutdown()

    def _shutdown(self):
        self._instance.stop_serving()
        self._background.stop()
        self._runs.wait_for_exit(5000)
        self._scheduler.stop()
        self._peer_timer.stop()
        self._tray.hide()
        self._app.quit()
