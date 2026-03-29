import unittest
from datetime import datetime

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtTest import QSignalSpy

from gui.scheduler import PipelineScheduler

_app = QApplication.instance() or QApplication([])


class TestPipelineScheduler(unittest.TestCase):

    def test_emits_run_requested_on_timer_tick(self):
        # interval_minutes=0 is testing mode: fires immediately
        scheduler = PipelineScheduler(interval_minutes=0)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.start()

        loop = QEventLoop()
        QTimer.singleShot(150, loop.quit)
        loop.exec()
        scheduler.stop()

        self.assertGreaterEqual(len(spy), 1)
        self.assertEqual(spy[0][0], "scheduled")

    def test_suppresses_tick_when_running(self):
        scheduler = PipelineScheduler(interval_minutes=0)

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

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.mark_running()
        scheduler.start()

        loop = QEventLoop()
        QTimer.singleShot(80, loop.quit)
        loop.exec()
        self.assertEqual(len(spy), 0)

        # mark_idle calls _schedule_next, which fires immediately in test mode
        scheduler.mark_idle()
        loop2 = QEventLoop()
        QTimer.singleShot(100, loop2.quit)
        loop2.exec()
        scheduler.stop()

        self.assertGreaterEqual(len(spy), 1)

    def test_pause_and_resume(self):
        scheduler = PipelineScheduler(interval_minutes=0)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.start()
        scheduler.pause()

        loop = QEventLoop()
        QTimer.singleShot(100, loop.quit)
        loop.exec()
        # The first tick may or may not have fired before pause — just check pause works
        count_after_pause = len(spy)

        scheduler.resume()
        loop2 = QEventLoop()
        QTimer.singleShot(100, loop2.quit)
        loop2.exec()
        scheduler.stop()

        self.assertGreater(len(spy), count_after_pause)

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
        self.assertEqual(scheduler.interval_minutes, 10)
        scheduler.set_interval_minutes(5)
        self.assertEqual(scheduler.interval_minutes, 5)

    def test_next_run_at_is_clock_aligned(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        scheduler.start()

        nra = scheduler.next_run_at
        self.assertIsNotNone(nra)
        self.assertEqual(nra.minute % 10, 0)
        self.assertEqual(nra.second, 0)
        self.assertEqual(nra.microsecond, 0)
        scheduler.stop()

    def test_next_run_at_is_none_when_paused(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        scheduler.start()
        scheduler.pause()
        self.assertIsNone(scheduler.next_run_at)

    def test_status_changed_emitted_on_start(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        spy = QSignalSpy(scheduler.status_changed)
        scheduler.start()
        self.assertGreaterEqual(len(spy), 1)
        scheduler.stop()

    def test_status_changed_emitted_on_pause(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        scheduler.start()
        spy = QSignalSpy(scheduler.status_changed)
        scheduler.pause()
        self.assertGreaterEqual(len(spy), 1)


if __name__ == "__main__":
    unittest.main()
