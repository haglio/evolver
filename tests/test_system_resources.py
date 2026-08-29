"""Tests for util.system_resources.

The two live tests at the bottom read the real machine and only prove the
numbers are in-range on Windows. The unit conversions -- bytes to GB, tick
stamps to seconds, the 32-bit wrap -- feed the non-AI stage's decision to
start or suspend a multi-hour encode, so they are pinned exactly at the
Win32 boundary with the structures filled by hand; those tests run on any
platform.
"""

import unittest

import pytest

from util import system_resources


def _fills(**fields):
    """A Win32 stand-in that writes *fields* into the caller's structure."""
    def fake(ref):
        for name, value in fields.items():
            setattr(ref._obj, name, value)
        return 1
    return fake


class TestAvailableRamConversion:

    def test_avail_phys_bytes_come_back_as_gb(self, monkeypatch):
        monkeypatch.setattr(
            system_resources.ctypes.windll.kernel32, "GlobalMemoryStatusEx",
            _fills(ullAvailPhys=6 * 1024**3),
        )
        assert system_resources.available_ram_gb() == 6.0

    def test_the_conversion_is_binary_gb_not_a_rounded_guess(self, monkeypatch):
        # A GB-vs-GiB slip (a factor of 1.074) is exactly what the wide live
        # bounds could never catch.
        monkeypatch.setattr(
            system_resources.ctypes.windll.kernel32, "GlobalMemoryStatusEx",
            _fills(ullAvailPhys=3 * 1024**3 + 512 * 1024**2),
        )
        assert system_resources.available_ram_gb() == 3.5

    def test_a_failing_call_raises_instead_of_reporting_zero_ram(self, monkeypatch):
        monkeypatch.setattr(
            system_resources.ctypes.windll.kernel32, "GlobalMemoryStatusEx",
            lambda ref: 0,
        )
        with pytest.raises(OSError):
            system_resources.available_ram_gb()


class TestSecondsSinceLastInputConversion:

    def _patched_idle(self, monkeypatch, last_input_ticks, now_ticks):
        monkeypatch.setattr(
            system_resources.ctypes.windll.user32, "GetLastInputInfo",
            _fills(dwTime=last_input_ticks),
        )
        monkeypatch.setattr(
            system_resources.ctypes.windll.kernel32, "GetTickCount",
            lambda: now_ticks,
        )
        return system_resources.seconds_since_last_input()

    def test_tick_millis_come_back_as_seconds(self, monkeypatch):
        assert self._patched_idle(monkeypatch, 1000, 31000) == 30.0

    def test_the_49_day_tick_wrap_still_reads_as_a_short_idle(self, monkeypatch):
        # Input landed just before GetTickCount wrapped; now is just after.
        # Signed arithmetic would answer -49.7 days; the 32-bit difference
        # answers the true 8.192 s.
        assert self._patched_idle(monkeypatch, 0xFFFFF000, 4096) == pytest.approx(8.192)

    def test_a_failing_call_raises_instead_of_reporting_idle(self, monkeypatch):
        monkeypatch.setattr(
            system_resources.ctypes.windll.user32, "GetLastInputInfo",
            lambda ref: 0,
        )
        with pytest.raises(OSError):
            system_resources.seconds_since_last_input()


class TestAvailableRam(unittest.TestCase):
    def test_reports_a_plausible_available_amount(self):
        available = system_resources.available_ram_gb()
        self.assertGreater(available, 0.0)
        self.assertLess(available, 4096.0)


class TestSecondsSinceLastInput(unittest.TestCase):
    def test_returns_a_nonnegative_plausible_number(self):
        idle = system_resources.seconds_since_last_input()
        self.assertIsInstance(idle, float)
        self.assertGreaterEqual(idle, 0.0)
        # A real session is never idle for weeks; a wildly large value would
        # mean the GetTickCount wrap arithmetic went wrong.
        self.assertLess(idle, 60 * 60 * 24 * 30)


if __name__ == "__main__":
    unittest.main()
