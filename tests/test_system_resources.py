from __future__ import annotations

import inspect
import unittest

import pytest

from util import system_resources


def _fills(**fields):
    def fake(ref):
        for name, value in fields.items():
            setattr(ref._obj, name, value)
        return 1
    return fake


class TestCpuBusyPercentSurface:
    def test_the_sample_window_has_to_be_named_by_the_caller_so_configs_value_has_no_second_copy(self):
        assert (
            inspect.signature(
                system_resources.measure_cpu_busy_percent
            ).parameters["sample_seconds"].default
            is inspect.Parameter.empty
        )

    def test_the_name_says_it_takes_time(self):
        assert not hasattr(system_resources, "cpu_busy_percent")


class TestAvailableRamConversion:

    def test_avail_phys_bytes_come_back_as_gb(self, monkeypatch):
        monkeypatch.setattr(
            system_resources.ctypes.windll.kernel32, "GlobalMemoryStatusEx",
            _fills(ullAvailPhys=6 * 1024**3),
        )
        assert system_resources.available_ram_gb() == 6.0

    def test_the_conversion_is_binary_gb_since_it_decides_whether_an_hours_long_encode_starts(self, monkeypatch):
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
        assert available > 0.0
        assert available < 4096.0


class TestMeasuringTheCpu:
    def test_a_clock_that_did_not_move_reads_as_idle(self):
        assert system_resources.measure_cpu_busy_percent(0.0, read_times=lambda: (10, 20, 30)) == 0.0
