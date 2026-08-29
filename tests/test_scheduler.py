import unittest

from PyQt6.QtTest import QSignalSpy

from gui.scheduler import PipelineScheduler



class TestPipelineScheduler(unittest.TestCase):

    def test_emits_run_requested_on_timer_tick(self):
        """The one end-to-end timer test: the real QTimer wiring, waited on by
        deadline rather than a fixed sleep. interval_minutes=0 is testing
        mode and fires immediately."""
        scheduler = PipelineScheduler(interval_minutes=0)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.start()
        fired = spy.wait(5000)
        scheduler.stop()

        self.assertTrue(fired, "the scheduler's timer never fired")
        self.assertEqual(spy[0][0], "scheduled")

    # The remaining tick behaviour is driven by calling tick() -- the slot the
    # timer fires -- directly, so each test asserts an exact signal count
    # instead of hoping a wall-clock window was long enough (these four were
    # the slowest tests in the whole suite, and the pause/resume one carried a
    # comment documenting its own nondeterminism).

    def test_suppresses_tick_when_running(self):
        scheduler = PipelineScheduler(interval_minutes=10)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.mark_running()
        scheduler.tick()
        scheduler.stop()

        self.assertEqual(len(spy), 0)

    def test_resumes_after_mark_idle(self):
        scheduler = PipelineScheduler(interval_minutes=10)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.mark_running()
        scheduler.tick()
        self.assertEqual(len(spy), 0)

        scheduler.mark_idle()  # reopens scheduling
        scheduler.tick()
        scheduler.stop()

        self.assertEqual(len(spy), 1)

    def test_pause_and_resume(self):
        scheduler = PipelineScheduler(interval_minutes=10)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.start()
        scheduler.pause()
        # Paused means no tick is scheduled at all -- the timer is stopped and
        # the next-run display goes blank.
        self.assertIsNone(scheduler.next_run_at)

        scheduler.resume()
        self.assertIsNotNone(scheduler.next_run_at)
        scheduler.tick()
        scheduler.stop()

        self.assertEqual(len(spy), 1)
        self.assertEqual(spy[0][0], "scheduled")

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
