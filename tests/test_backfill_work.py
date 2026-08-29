import threading
import unittest
from unittest.mock import patch

from backfill.work import SerialWorker


class TestSerialWorker(unittest.TestCase):
    def _worker(self):
        worker = SerialWorker()
        self.addCleanup(worker.shutdown)
        return worker

    def test_a_submitted_task_runs_off_the_calling_thread(self):
        worker = self._worker()
        ran_on = []

        worker.submit(lambda: ran_on.append(threading.current_thread()))
        worker.drain()

        self.assertEqual(len(ran_on), 1)
        self.assertIsNot(ran_on[0], threading.current_thread())

    def test_tasks_run_in_the_order_they_were_submitted(self):
        worker = self._worker()
        order = []

        for index in range(20):
            worker.submit(lambda index=index: order.append(index))
        worker.drain()

        self.assertEqual(order, list(range(20)))

    def test_draining_waits_for_every_submitted_task(self):
        worker = self._worker()
        done = []

        worker.submit(lambda: done.append("slow"))
        worker.drain()

        self.assertEqual(done, ["slow"])

    def test_draining_with_nothing_submitted_returns(self):
        worker = self._worker()
        worker.drain()
        self.assertIsNone(worker._latest)  # nothing was ever waited on

    def test_a_failing_task_is_logged_and_never_reaches_the_caller(self):
        worker = self._worker()

        def boom():
            raise RuntimeError("disk on fire")

        with patch("backfill.work.log") as log:
            worker.submit(boom)
            worker.drain()

        log.exception.assert_called_once()

    def test_a_failing_task_does_not_stop_the_ones_behind_it(self):
        worker = self._worker()
        done = []

        def boom():
            raise RuntimeError("disk on fire")

        with patch("backfill.work.log"):
            worker.submit(boom)
            worker.submit(lambda: done.append("after"))
            worker.drain()

        self.assertEqual(done, ["after"])


if __name__ == "__main__":
    unittest.main()
