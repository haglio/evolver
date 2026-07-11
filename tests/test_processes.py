import os
import subprocess
import sys
import unittest

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
