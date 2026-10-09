from __future__ import annotations

import unittest
from unittest.mock import Mock, call, patch

import review_weird_app


class TestMain(unittest.TestCase):
    def test_the_window_is_shown_and_its_lines_go_to_evolvers_log(self):
        with patch("review_weird_app.evolver.setup_logging") as logging_set_up, \
             patch("review_weird_app.QApplication") as application, \
             patch("review_weird_app.process_identity.claim"), \
             patch("review_weird_app.ReviewWeirdWindow") as window:
            application.return_value.exec.return_value = 0

            exit_code = review_weird_app.main()

        logging_set_up.assert_called_once_with()
        window.return_value.show.assert_called_once_with()
        self.assertEqual(exit_code, 0)

    def test_it_is_evolver_on_the_taskbar_before_its_window_exists(self):
        order = Mock()
        with patch("review_weird_app.evolver.setup_logging"), \
             patch("review_weird_app.QApplication") as application, \
             patch("review_weird_app.process_identity.claim") as claim, \
             patch("review_weird_app.ReviewWeirdWindow") as window:
            order.attach_mock(claim, "claim")
            order.attach_mock(window, "window")
            application.return_value.exec.return_value = 0

            review_weird_app.main()

        self.assertEqual(order.mock_calls[:2], [call.claim(application.return_value), call.window()])


if __name__ == "__main__":
    unittest.main()
