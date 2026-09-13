from __future__ import annotations

import unittest
from unittest.mock import patch

from gui.run_record import RunRecord
from gui.sign_in_notice import SignInNotice


def a_run(*stages):
    return RunRecord(id="r", started_at="2026-01-01T00:00:00", finished_at="2026-01-01T00:00:10",
                     duration_seconds=10.0, trigger="scheduled", status="success",
                     stages=list(stages))


UPSCALE_HELD_FOR_SIGN_IN = {"name": "upscale", "status": "skipped", "duration_seconds": 0.0,
                            "result": None, "skip_reason": "topaz_sign_in_expired"}


class TestSignInNotice(unittest.TestCase):
    def test_a_run_that_held_upscaling_for_the_topaz_sign_in_tells_the_user(self):
        with patch("gui.sign_in_notice.show_error") as show_error:
            SignInNotice().after_run(a_run(UPSCALE_HELD_FOR_SIGN_IN), now=0.0)

        show_error.assert_called_once()

    def test_a_non_ai_upscale_waiting_for_the_topaz_sign_in_tells_the_user_too(self):
        waiting = {"name": "upscale_non_ai", "status": "completed", "duration_seconds": 1.0,
                   "result": {"start_deferred": "topaz_sign_in_expired", "in_flight": ""}}
        with patch("gui.sign_in_notice.show_error") as show_error:
            SignInNotice().after_run(a_run(waiting), now=0.0)

        show_error.assert_called_once()

    def test_the_user_is_told_once_a_day_not_once_a_run(self):
        notice = SignInNotice()
        with patch("gui.sign_in_notice.show_error") as show_error:
            notice.after_run(a_run(UPSCALE_HELD_FOR_SIGN_IN), now=0.0)
            notice.after_run(a_run(UPSCALE_HELD_FOR_SIGN_IN), now=600.0)
            self.assertEqual(show_error.call_count, 1)

            notice.after_run(a_run(UPSCALE_HELD_FOR_SIGN_IN), now=24 * 3600.0)
            self.assertEqual(show_error.call_count, 2)

    def test_a_run_that_held_nothing_back_for_the_sign_in_says_nothing(self):
        nothing_to_do = {"name": "upscale", "status": "skipped", "duration_seconds": 0.0,
                         "result": None, "skip_reason": "no_pending_work"}
        user_present = {"name": "upscale_non_ai", "status": "completed", "duration_seconds": 1.0,
                        "result": {"start_deferred": "user_present", "in_flight": ""}}
        with patch("gui.sign_in_notice.show_error") as show_error:
            SignInNotice().after_run(a_run(nothing_to_do, user_present), now=0.0)

        show_error.assert_not_called()

    def test_a_run_finishing_while_the_message_is_still_open_does_not_open_a_second(self):
        notice = SignInNotice()
        held = a_run(UPSCALE_HELD_FOR_SIGN_IN)

        def next_run_finishes_meanwhile(*_):
            notice.after_run(held, now=600.0)

        with patch("gui.sign_in_notice.show_error",
                   side_effect=next_run_finishes_meanwhile) as show_error:
            notice.after_run(held, now=0.0)

        show_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
