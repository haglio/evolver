from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from PySide6.QtTest import QSignalSpy

from gui.scheduler import PipelineScheduler


class TestPipelineScheduler(unittest.TestCase):

    def test_the_real_timer_requests_a_run_at_the_slot(self):
        a_millisecond_short_of_a_slot = datetime(2026, 1, 1, 12, 10, tzinfo=UTC) - timedelta(milliseconds=1)
        scheduler = PipelineScheduler(interval_minutes=10, now=lambda: a_millisecond_short_of_a_slot)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.start()
        fired = spy.wait(5000)
        scheduler.stop()

        assert fired, "the scheduler's timer never fired"
        assert spy.at(0)[0] == "scheduled"

    def test_suppresses_tick_when_running(self):
        scheduler = PipelineScheduler(interval_minutes=10)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.mark_running()
        scheduler.tick()
        scheduler.stop()

        assert spy.count() == 0

    def test_a_tick_mid_run_schedules_nothing(self):
        scheduler = PipelineScheduler(interval_minutes=10,
                                      now=lambda: datetime(2026, 1, 1, 8, 3, tzinfo=UTC))
        scheduler.mark_running()

        scheduler.tick()
        mid_run = scheduler.next_run_at
        scheduler.stop()

        assert mid_run is None, "the run's end schedules the next tick"

    def test_the_runs_end_schedules_the_next_tick(self):
        scheduler = PipelineScheduler(interval_minutes=10,
                                      now=lambda: datetime(2026, 1, 1, 8, 3, tzinfo=UTC))
        scheduler.mark_running()

        scheduler.mark_idle()
        after_the_run = scheduler.next_run_at
        scheduler.stop()

        assert after_the_run == datetime(2026, 1, 1, 8, 10, tzinfo=UTC)

    def test_resumes_after_mark_idle(self):
        scheduler = PipelineScheduler(interval_minutes=10)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.mark_running()
        scheduler.tick()
        assert spy.count() == 0

        scheduler.mark_idle()
        scheduler.tick()
        scheduler.stop()

        assert spy.count() == 1

    def test_toggling_pauses_a_running_schedule_and_resumes_a_paused_one(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        scheduler.start()

        scheduler.toggle_pause()
        assert scheduler.is_paused
        assert scheduler.next_run_at is None

        scheduler.toggle_pause()
        assert not scheduler.is_paused
        assert scheduler.next_run_at is not None
        scheduler.stop()

    def test_pause_and_resume(self):
        scheduler = PipelineScheduler(interval_minutes=10)

        spy = QSignalSpy(scheduler.run_requested)
        scheduler.start()
        scheduler.pause()
        assert scheduler.next_run_at is None

        scheduler.resume()
        assert scheduler.next_run_at is not None
        scheduler.tick()
        scheduler.stop()

        assert spy.count() == 1
        assert spy.at(0)[0] == "scheduled"

    def test_run_now_emits_manual_trigger(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        spy = QSignalSpy(scheduler.run_requested)

        scheduler.run_now()

        assert spy.count() == 1
        assert spy.at(0)[0] == "manual"

    def test_run_now_suppressed_when_running(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        spy = QSignalSpy(scheduler.run_requested)

        scheduler.mark_running()
        scheduler.run_now()

        assert spy.count() == 0

    def test_set_interval(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        assert scheduler.interval_minutes == 10
        scheduler.set_interval_minutes(5)
        assert scheduler.interval_minutes == 5

    def test_next_run_at_is_clock_aligned(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        scheduler.start()

        nra = scheduler.next_run_at
        assert nra is not None
        assert nra.minute % 10 == 0
        assert nra.second == 0
        assert nra.microsecond == 0
        scheduler.stop()

    def test_the_slot_after_the_last_one_of_the_day_is_midnight_of_the_next_day(self):
        late = datetime(2026, 1, 1, 23, 55, tzinfo=UTC)
        scheduler = PipelineScheduler(interval_minutes=10, now=lambda: late)
        scheduler.start()

        assert scheduler.next_run_at == datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
        scheduler.stop()

    def test_next_run_at_is_none_when_paused(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        scheduler.start()
        scheduler.pause()
        assert scheduler.next_run_at is None

    def test_status_changed_emitted_on_start(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        spy = QSignalSpy(scheduler.status_changed)
        scheduler.start()
        assert spy.count() >= 1
        scheduler.stop()

    def test_status_changed_emitted_on_pause(self):
        scheduler = PipelineScheduler(interval_minutes=10)
        scheduler.start()
        spy = QSignalSpy(scheduler.status_changed)
        scheduler.pause()
        assert spy.count() >= 1


if __name__ == "__main__":
    unittest.main()
