import unittest
from unittest.mock import patch

from util import windows_alert


class TestWindowsAlert(unittest.TestCase):
    @patch("util.windows_alert.ctypes.windll.user32.MessageBoxW", create=True)
    def test_show_error_window_calls_message_box_with_error_icon(self, message_box):
        message_box.return_value = 1

        windows_alert.show_error_window("Title", "Body")

        message_box.assert_called_once_with(0, "Body", "Title", 0x10)


if __name__ == "__main__":
    unittest.main()
