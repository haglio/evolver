"""Tests for gui.startup — the Start-with-Windows shortcut.

The shortcut is written by generating a VBScript and running it through
cscript, so the observable surface off Windows is the script text and the
cscript invocation; both are captured at the subprocess boundary. The
Startup folder itself is redirected through APPDATA into a temp tree.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from gui import startup
from tests.temp_helpers import workspace_temp_dir


@pytest.fixture
def startup_dir():
    with workspace_temp_dir() as tmp, patch.dict("os.environ", {"APPDATA": str(tmp)}):
        folder = tmp / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        folder.mkdir(parents=True)
        yield folder


def _capture_cscript(captured):
    """A subprocess.run stand-in that reads the script before it is deleted."""
    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["script"] = Path(argv[2]).read_text(encoding="utf-8")
        captured["script_path"] = Path(argv[2])
        return subprocess.CompletedProcess(argv, 0)
    return fake_run


class TestRegisterStartup:

    def test_the_script_points_the_shortcut_at_the_tray_app(self, startup_dir):
        captured = {}
        with patch("gui.startup.subprocess.run", side_effect=_capture_cscript(captured)):
            startup.register_startup()

        project_dir = Path(startup.__file__).resolve().parent.parent
        script = captured["script"]
        assert f'CreateShortCut("{startup_dir / "Evolver.lnk"}")' in script
        assert f'oLink.TargetPath = "{sys.executable}"' in script
        assert f'oLink.Arguments = "{project_dir / "tray_app.py"}"' in script
        assert f'oLink.WorkingDirectory = "{project_dir}"' in script
        assert "oLink.Save" in script

    def test_the_script_is_run_through_cscript_quietly(self, startup_dir):
        captured = {}
        with patch("gui.startup.subprocess.run", side_effect=_capture_cscript(captured)):
            startup.register_startup()

        assert captured["argv"][0] == "cscript"
        assert captured["argv"][1] == "//Nologo"
        assert captured["argv"][2].endswith(".vbs")

    def test_the_temp_script_is_removed_afterwards(self, startup_dir):
        captured = {}
        with patch("gui.startup.subprocess.run", side_effect=_capture_cscript(captured)):
            startup.register_startup()

        assert not captured["script_path"].exists()

    def test_the_temp_script_is_removed_even_when_cscript_fails(self, startup_dir):
        captured = {}

        def failing_run(argv, **kwargs):
            captured["script_path"] = Path(argv[2])
            raise subprocess.CalledProcessError(1, argv)

        with patch("gui.startup.subprocess.run", side_effect=failing_run):
            with pytest.raises(subprocess.CalledProcessError):
                startup.register_startup()

        assert not captured["script_path"].exists()


class TestUnregisterStartup:

    def test_removes_the_shortcut(self, startup_dir):
        (startup_dir / "Evolver.lnk").write_bytes(b"shortcut")
        assert startup.is_registered()

        startup.unregister_startup()

        assert not startup.is_registered()
        assert not (startup_dir / "Evolver.lnk").exists()

    def test_is_a_noop_when_no_shortcut_exists(self, startup_dir):
        assert not startup.is_registered()
        startup.unregister_startup()  # must not raise
        assert not startup.is_registered()
