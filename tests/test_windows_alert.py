import unittest
from unittest.mock import Mock, patch

from util import windows_alert


class TestWindowsAlert(unittest.TestCase):
    @patch("util.windows_alert._send_msg")
    @patch("util.windows_alert._get_active_users")
    @patch("util.windows_alert._is_session_zero", return_value=False)
    @patch("util.windows_alert.ctypes.windll.user32.MessageBoxW", create=True)
    def test_show_error_window_uses_message_box_for_interactive_session(
        self,
        message_box,
        is_session_zero,
        get_active_users,
        send_msg,
    ):
        message_box.return_value = 1

        windows_alert.show_error_window("Title", "Body")

        message_box.assert_called_once()
        get_active_users.assert_not_called()
        send_msg.assert_not_called()

    @patch("util.windows_alert._send_msg")
    @patch("util.windows_alert._get_active_users", return_value=["Alex", "otheruser"])
    @patch("util.windows_alert._is_session_zero", return_value=True)
    def test_show_error_window_uses_first_successful_msg_target(
        self,
        is_session_zero,
        get_active_users,
        send_msg,
    ):
        send_msg.side_effect = [False, True]

        windows_alert.show_error_window("Title", "Body")

        send_msg.assert_any_call("Alex", "Title", "Title. See evolver.log for details.")
        send_msg.assert_any_call("otheruser", "Title", "Title. See evolver.log for details.")
        self.assertEqual(send_msg.call_count, 2)

    @patch("util.windows_alert.subprocess.run")
    def test_send_msg_returns_true_on_zero_exit_code(self, subprocess_run):
        subprocess_run.return_value = Mock(returncode=0, stdout="", stderr="")

        ok = windows_alert._send_msg("Alex", "Title", "Body")

        self.assertTrue(ok)
        subprocess_run.assert_called_once_with(
            ["msg", "Alex", "/TIME:5", "Title: Body"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    @patch("util.windows_alert._send_msg")
    @patch("util.windows_alert._get_active_users")
    @patch("util.windows_alert._is_session_zero", return_value=False)
    @patch("util.windows_alert.ctypes.windll.user32.MessageBoxW", create=True)
    def test_show_info_window_uses_info_icon_for_interactive_session(
        self,
        message_box,
        is_session_zero,
        get_active_users,
        send_msg,
    ):
        message_box.return_value = 1

        windows_alert.show_info_window("Title", "Body")

        message_box.assert_called_once_with(0, "Body", "Title", 0x40)
        get_active_users.assert_not_called()
        send_msg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
