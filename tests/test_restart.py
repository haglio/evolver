"""Starting Evolver again only once this copy has ended."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from gui import restart

on_windows = pytest.mark.skipif(sys.platform != "win32", reason="the Windows script host")


@on_windows
def test_the_launcher_runs_once_the_copy_it_waited_for_has_ended(tmp_path: Path):
    ran = tmp_path / "launcher.ran"
    launcher = tmp_path / "launch_example.vbs"
    launcher.write_text(
        'CreateObject("Scripting.FileSystemObject").CreateTextFile("' + str(ran) + '", True).Close\n',
        encoding="ascii")
    ending = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])

    restart.start_again_after(ending.pid, launcher)
    time.sleep(1)
    started_too_early = ran.exists()
    ending.wait()
    deadline = time.monotonic() + 30
    while not ran.exists() and time.monotonic() < deadline:
        time.sleep(0.1)

    assert not started_too_early
    assert ran.exists()


def test_the_wait_runs_on_the_plain_interpreter_not_out_of_this_checkouts_venv(tmp_path: Path):
    started = []

    restart.start_again_after(1234, tmp_path / "launch_example.vbs",
                              popen=lambda command, **kwargs: started.append(command))

    assert Path(started[0][0]) == Path(sys._base_executable).with_name("pythonw.exe")
    assert started[0][-2:] == ["1234", str(tmp_path / "launch_example.vbs")]
