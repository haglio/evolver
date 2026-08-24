"""What a bound Win32 handle does on a machine that could not bind it.

The Windows suite never reaches these paths — there ``WIN32_AVAILABLE`` is true
and every handle is the real one — so these cases force the flag down and drive
the refusal directly.  They are the only thing keeping that refusal honest; a
stand-in that quietly returned zero would pass every other test in the repo.
"""

import ctypes
import ctypes.wintypes
import unittest
from unittest.mock import patch

from util import win32_loader


class TestAvailability(unittest.TestCase):
    def test_the_flag_says_whether_this_ctypes_can_bind_a_dll(self):
        self.assertEqual(win32_loader.WIN32_AVAILABLE, hasattr(ctypes, "windll"))


class TestAStandInDll(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(win32_loader, "WIN32_AVAILABLE", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_call_that_reaches_an_unbound_entry_point_names_it(self):
        """The stand-in must never pass for a call that worked."""
        kernel32 = win32_loader.load_dll("kernel32")

        with self.assertRaises(win32_loader.Win32Unavailable) as caught:
            kernel32.OpenProcess(0x1000, False, 1234)

        self.assertIn("kernel32.OpenProcess", str(caught.exception))

    def test_an_unbound_entry_point_still_takes_the_argtypes_declared_on_it(self):
        """Modules declare argtypes at import; that has to survive too."""
        kernel32 = win32_loader.load_dll("kernel32")

        kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD]
        kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE

        self.assertEqual(kernel32.OpenProcess.argtypes, [ctypes.wintypes.DWORD])
        self.assertIs(kernel32.OpenProcess.restype, ctypes.wintypes.HANDLE)

    def test_an_unbound_entry_point_is_the_same_object_every_time(self):
        """A test that patches one has to be patching what the code will call."""
        ntdll = win32_loader.load_dll("ntdll")

        self.assertIs(ntdll.NtSuspendProcess, ntdll.NtSuspendProcess)


if __name__ == "__main__":
    unittest.main()
