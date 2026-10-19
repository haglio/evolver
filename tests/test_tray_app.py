"""tray_app.main: the application Evolver runs on is one made where it is let go of safely."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

import tray_app


def test_evolver_runs_on_an_application_made_where_it_is_let_go_of_safely():
    made, ran_on = [], []

    @contextmanager
    def application(argv):
        made.append(argv)
        yield "the application"

    class _Evolver:
        def __init__(self, app):
            ran_on.append(app)

        def run(self) -> int:
            return 7

    with patch("shared_ui.application.application", application), \
            patch("gui.app.EvolverApp", _Evolver), \
            patch("tray_app.crash_log"), patch("tray_app.atexit"), \
            patch("tray_app._name_this_process"), \
            pytest.raises(SystemExit) as exited:
        tray_app.main()

    assert len(made) == 1
    assert ran_on == ["the application"]
    assert exited.value.code == 7
