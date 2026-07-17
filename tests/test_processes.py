import os
import subprocess
import sys
import unittest
from pathlib import Path

from util import processes


class TestIsRunning(unittest.TestCase):
    def test_true_for_current_process(self):
        self.assertTrue(processes.is_running(os.getpid()))

    def test_false_after_process_exits(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"], creationflags=subprocess.CREATE_NO_WINDOW
        )
        proc.wait()
        self.assertFalse(processes.is_running(proc.pid))


class TestImagePath(unittest.TestCase):
    def test_names_the_current_interpreter(self):
        path = processes.image_path(os.getpid())
        self.assertIsNotNone(path)
        self.assertIn("python", path.lower())

    def test_none_for_dead_process(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"], creationflags=subprocess.CREATE_NO_WINDOW
        )
        proc.wait()
        self.assertIsNone(processes.image_path(proc.pid))


class TestPidsOfImage(unittest.TestCase):
    def test_finds_the_current_interpreter_by_its_image(self):
        # Probe with the process's real image, not sys.executable: a Windows
        # venv python.exe is a redirect stub whose backing image is the base
        # interpreter (e.g. C:\Python314\python.exe), so QueryFullProcessImageName
        # reports that, and pids_of_image(sys.executable) never matches us.
        image = processes.image_path(os.getpid())
        self.assertIsNotNone(image)
        self.assertIn(os.getpid(), processes.pids_of_image(Path(image)))

    def test_empty_for_an_absent_executable(self):
        pids = processes.pids_of_image(Path(r"C:\does\not\exist\nowhere.exe"))
        self.assertEqual(pids, [])


class TestCommandLine(unittest.TestCase):
    def test_reads_a_child_processes_arguments(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            cmdline = processes.command_line(proc.pid)
            self.assertIsNotNone(cmdline)
            self.assertIn("time.sleep(60)", cmdline)
        finally:
            proc.kill()
            proc.wait(timeout=10)

    def test_none_for_dead_process(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"], creationflags=subprocess.CREATE_NO_WINDOW
        )
        proc.wait()
        self.assertIsNone(processes.command_line(proc.pid))


class TestTerminate(unittest.TestCase):
    def test_kills_a_live_process(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            self.assertTrue(processes.terminate(proc.pid))
            proc.wait(timeout=10)
            self.assertFalse(processes.is_running(proc.pid))
        finally:
            proc.kill()


if __name__ == "__main__":
    unittest.main()
