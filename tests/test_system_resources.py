"""Tests for util.system_resources.

The two live tests at the end read the real machine and only prove the
numbers are in-range on Windows. The unit conversions -- bytes to GB, tick
stamps to seconds, the 32-bit wrap -- feed the non-AI stage's decision to
start or suspend a multi-hour encode, so they are pinned exactly at the
Win32 boundary with the structures filled by hand; those tests run on any
platform.
"""
from __future__ import annotations

import inspect
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


class TestCpuBusyPercentSurface:
    def test_the_sample_window_has_to_be_named_by_the_caller(self):
        """The one caller passes `config.CPU_BUSY_SKIP_SAMPLE_SECONDS`; a
        default here would be a second copy of that tuning value, free to
        disagree with it."""
        assert (
            inspect.signature(
                system_resources.measure_cpu_busy_percent
            ).parameters["sample_seconds"].default
            is inspect.Parameter.empty
        )

    def test_the_name_says_it_takes_time(self):
        """It reads like a property lookup and blocks for the sample window by
        construction -- two samples of counters that are totals, with a sleep
        between them."""
        assert not hasattr(system_resources, "cpu_busy_percent")


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
        with pytest.raises(OSError, match="GlobalMemoryStatusEx failed"):
            system_resources.available_ram_gb()


class TestAvailableRam(unittest.TestCase):
    def test_reports_a_plausible_available_amount(self):
        available = system_resources.available_ram_gb()
        self.assertGreater(available, 0.0)
        self.assertLess(available, 4096.0)
