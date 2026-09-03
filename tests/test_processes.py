import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from util import processes


class TestIsRunning:
    def test_true_for_current_process(self):
        assert processes.is_running(os.getpid())

    def test_false_after_process_exits(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"], creationflags=subprocess.CREATE_NO_WINDOW
        )
        proc.wait()
        assert not processes.is_running(proc.pid)


class TestImagePath:
    def test_names_the_current_interpreter(self):
        path = processes.image_path(os.getpid())
        assert path is not None
        assert "python" in path.lower()

    def test_none_for_dead_process(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"], creationflags=subprocess.CREATE_NO_WINDOW
        )
        proc.wait()
        assert processes.image_path(proc.pid) is None


class TestPidsOfImage:
    def test_finds_the_current_interpreter_by_its_image(self):
        # Probe with the process's real image, not sys.executable: a Windows
        # venv python.exe is a redirect stub whose backing image is the base
        # interpreter (e.g. C:\Python314\python.exe), so QueryFullProcessImageName
        # reports that, and pids_of_image(sys.executable) never matches us.
        image = processes.image_path(os.getpid())
        assert image is not None
        assert os.getpid() in processes.pids_of_image(Path(image))

    def test_empty_for_an_absent_executable(self):
        pids = processes.pids_of_image(Path(r"C:\does\not\exist\nowhere.exe"))
        assert pids == []


class TestCommandLine:
    def test_reads_a_child_processes_arguments(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            cmdline = processes.command_line(proc.pid)
            assert cmdline is not None
            assert "time.sleep(60)" in cmdline
        finally:
            proc.kill()
            proc.wait(timeout=10)

    def test_none_for_dead_process(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"], creationflags=subprocess.CREATE_NO_WINDOW
        )
        proc.wait()
        assert processes.command_line(proc.pid) is None


class TestTerminate:
    def test_kills_a_live_process(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            assert processes.terminate(proc.pid)
            proc.wait(timeout=10)
            assert not processes.is_running(proc.pid)
        finally:
            proc.kill()


def _base_python():
    """The base interpreter, spawned directly.

    A venv's python.exe is a launcher that waits on a child doing the real work,
    and suspending the launcher would leave that child running. Topaz's ffmpeg
    (the real target) is a plain exe, so this only matters for the test.

    Asked for when a test needs it rather than while this module is imported:
    it is a Win32 call, and one made at import decides whether this file can be
    collected at all.
    """
    return processes.image_path(os.getpid())


_GROWING_FILE = (
    "import sys, time\n"
    "f = open(sys.argv[1], 'ab', buffering=0)\n"
    "while True:\n"
    "    f.write(b'x')\n"
    "    time.sleep(0.005)\n"
)


def _size(counter: Path) -> int:
    return counter.stat().st_size if counter.exists() else 0


def _wait_until(condition, deadline_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


class TestSuspendResume:
    def test_suspend_freezes_a_process_and_resume_thaws_it(self):
        with tempfile.TemporaryDirectory() as folder:
            counter = Path(folder) / "count.bin"
            proc = subprocess.Popen(
                [_base_python(), "-c", _GROWING_FILE, str(counter)],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                assert _wait_until(lambda: _size(counter) >= 3), \
                    "the child never started writing"

                assert processes.suspend(proc.pid)
                # A write already past the syscall boundary can still land, so
                # wait for quiescence by deadline instead of hoping a fixed
                # sleep was long enough (the old 0.3 s flaked on a loaded
                # runner). A healthy unsuspended child writes every 5 ms, so a
                # full second without growth cannot be scheduling noise.
                def _went_quiet():
                    before = _size(counter)
                    time.sleep(1.0)
                    return _size(counter) == before
                assert _wait_until(_went_quiet), "the suspended child kept writing"

                frozen = _size(counter)
                assert processes.resume(proc.pid)
                # Fail only if it never advances -- no fixed window to lose.
                assert _wait_until(lambda: _size(counter) > frozen), \
                    "the resumed child never wrote again"
            finally:
                proc.kill()
                proc.wait(timeout=10)

    def test_suspend_and_resume_return_false_for_a_dead_process(self):
        proc = subprocess.Popen(
            [_base_python(), "-c", "pass"], creationflags=subprocess.CREATE_NO_WINDOW
        )
        proc.wait()
        assert not processes.suspend(proc.pid)
        assert not processes.resume(proc.pid)
