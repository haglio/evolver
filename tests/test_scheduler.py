import unittest

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtTest import QSignalSpy

from gui.scheduler import PipelineScheduler

_app = QApplication.instance() or QApplication([])


class TestPipelineScheduler(unittest.TestCase):

    def test_emits_run_requested_on_timer_tick(self):
        scheduler = PipelineScheduler(interval_minutes=0)  # will set 100ms for testing
        scheduler._timer.setInterval(50)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.start()

        # Wait for at least one tick
        loop = QEventLoop()
        QTimer.singleShot(150, loop.quit)
        loop.exec()
        scheduler.stop()

        self.assertGreaterEqual(len(spy), 1)
        self.assertEqual(spy[0][0], "scheduled")

    def test_suppresses_tick_when_running(self):
        scheduler = PipelineScheduler(interval_minutes=0)
        scheduler._timer.setInterval(50)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.mark_running()
        scheduler.start()

        loop = QEventLoop()
        QTimer.singleShot(150, loop.quit)
        loop.exec()
        scheduler.stop()

        self.assertEqual(len(spy), 0)

    def test_resumes_after_mark_idle(self):
        scheduler = PipelineScheduler(interval_minutes=0)
        scheduler._timer.setInterval(50)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.mark_running()
        scheduler.start()

        # Let a tick pass while running
        loop = QEventLoop()
        QTimer.singleShot(80, loop.quit)
        loop.exec()
        self.assertEqual(len(spy), 0)

        # Now mark idle and wait for next tick
        scheduler.mark_idle()
        loop2 = QEventLoop()
        QTimer.singleShot(100, loop2.quit)
        loop2.exec()
        scheduler.stop()

        self.assertGreaterEqual(len(spy), 1)

    def test_pause_and_resume(self):
        scheduler = PipelineScheduler(interval_minutes=0)
        scheduler._timer.setInterval(50)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.start()
        scheduler.pause()

        loop = QEventLoop()
        QTimer.singleShot(150, loop.quit)
        loop.exec()
        self.assertEqual(len(spy), 0)

        scheduler.resume()
        loop2 = QEventLoop()
        QTimer.singleShot(100, loop2.quit)
        loop2.exec()
        scheduler.stop()

        self.assertGreaterEqual(len(spy), 1)

    def test_run_now_emits_manual_trigger(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        spy = QSignalSpy(scheduler.run_requested)

        scheduler.run_now()

        self.assertEqual(len(spy), 1)
        self.assertEqual(spy[0][0], "manual")

    def test_run_now_suppressed_when_running(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        spy = QSignalSpy(scheduler.run_requested)

        scheduler.mark_running()
        scheduler.run_now()

        self.assertEqual(len(spy), 0)

    def test_set_interval(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        self.assertEqual(scheduler._timer.interval(), 10 * 60 * 1000)
        scheduler.set_interval_minutes(5)
        self.assertEqual(scheduler._timer.interval(), 5 * 60 * 1000)


if __name__ == "__main__":
    unittest.main()
