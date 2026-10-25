from __future__ import annotations

from unittest.mock import patch

from app_support import loading_screen
from shared_ui import loading_process
from shared_ui.loading_window import Loading, LoadingCanceled

import config
from gui import app as evolver_app
from gui import process_identity
from gui.single_instance import Outcome
from tests.gui_support import build_evolver_app
from util.preview import shown_as


class _Loading:
    def __init__(self, happened: list[str], *, canceled: bool = False):
        self._happened = happened
        self._canceled = canceled

    def say(self, step: str) -> None:
        self._happened.append(f"said {step}")
        if self._canceled:
            raise LoadingCanceled

    def done(self) -> None:
        self._happened.append("done")


def _launch(request, outcome: Outcome, *, canceled: bool = False, app=None) -> tuple[int, list[str], int]:
    app = app or build_evolver_app(request)
    happened: list[str] = []
    with patch.object(Loading, "at_the_click", return_value=_Loading(happened, canceled=canceled)) as opened, \
         patch.object(app._instance, "take_over", return_value=outcome), \
         patch.object(app._instance, "serve_launches", side_effect=lambda **_: happened.append("listening")), \
         patch.object(app, "start", side_effect=lambda: happened.append("tray up")), \
         patch.object(app._app, "exec", return_value=0), \
         patch("gui.app.show_error"), \
         patch("gui.app.crash_log.write_info"):
        exit_code = app.run()
    return exit_code, happened, opened.call_count


def test_the_loading_screen_comes_up_once_this_launch_is_evolver_and_goes_once_its_tray_is_up(request):
    exit_code, happened, _opened = _launch(request, Outcome.CLAIMED)

    assert exit_code == 0
    assert happened == [*(f"said {step}" for step, _weight in evolver_app.STEPS), "listening", "tray up", "done"]


def test_a_launch_handed_to_the_evolver_already_running_opens_no_loading_screen(request):
    _exit_code, happened, opened = _launch(request, Outcome.HANDED_OFF)

    assert (happened, opened) == ([], 0)


def test_esc_on_the_loading_screen_starts_nothing(request):
    exit_code, happened, _opened = _launch(request, Outcome.CLAIMED, canceled=True)

    assert exit_code == 0
    assert happened == [f"said {evolver_app.STEPS[0][0]}"]


def test_the_loading_screen_runs_in_a_process_of_its_own_wearing_evolvers_taskbar_button():
    with patch.object(loading_process.LoadingProcess, "open") as opened:
        evolver_app.open_the_loading_screen()

    opened.assert_called_once_with(
        caption="Evolver Loading", wordmark="Evolver", icon=config.PROJECT_DIR / "icon.ico", preview=shown_as(),
        steps=evolver_app.STEPS, cancel_hint="Press Esc to cancel opening Evolver",
        app_id=process_identity.identity(), taskbar=process_identity.taskbar_app())


def test_a_launch_from_its_launcher_tells_its_loading_screen_how_big_its_window_is(request, tmp_path, monkeypatch):
    place = loading_screen.MeetingPlace(tmp_path / "screen", ())
    monkeypatch.setenv(loading_screen.FOLDER, str(place.folder))
    app = build_evolver_app(request)

    _launch(request, Outcome.CLAIMED, app=app)

    assert place.where_the_app_comes_up() == loading_screen.AppWindow(size=(app._window.width(), app._window.height()))
