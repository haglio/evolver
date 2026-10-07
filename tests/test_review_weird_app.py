from __future__ import annotations

import unittest
from unittest.mock import patch

import review_weird_app


class TestMain(unittest.TestCase):
    def test_the_window_is_shown_and_its_lines_go_to_evolvers_log(self):
        with patch("review_weird_app.evolver.setup_logging") as logging_set_up, \
             patch("review_weird_app.QApplication") as application, \
             patch("review_weird_app.ReviewWeirdWindow") as window:
            application.return_value.exec.return_value = 0

            exit_code = review_weird_app.main()

        logging_set_up.assert_called_once_with()
        window.return_value.show.assert_called_once_with()
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
