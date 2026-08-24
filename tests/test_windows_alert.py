import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_dead_code import PROJECT_ROOT, _source_files
from util import windows_alert


class TestTheOnlyWayToAModalDialog(unittest.TestCase):
    def test_no_other_module_reaches_message_box_w(self):
        """``tests/__init__.py`` gags the dialog at ``_message_box_w``.

        That gag covers this module and nothing else, so a second module
        calling ``MessageBoxW`` for itself would block an unattended run on a
        human — the failure the gag exists to make impossible.
        """
        callers = [
            name
            for name in _source_files(PROJECT_ROOT)
            if "MessageBoxW" in Path(PROJECT_ROOT, name).read_text(encoding="utf-8")
        ]

        self.assertEqual(callers, [str(Path("util", "windows_alert.py"))])


class TestWindowsAlert(unittest.TestCase):
    @patch("util.windows_alert._message_box_w")
    def test_show_error_window_calls_message_box_with_error_icon(self, message_box):
        message_box.return_value = 1

        windows_alert.show_error_window("Title", "Body")

        message_box.assert_called_once_with(0, "Body", "Title", 0x10)


if __name__ == "__main__":
    unittest.main()
