"""System resource helpers used by the scheduled pipeline."""

import ctypes
import shutil
import time
from pathlib import Path


class _FileTime(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", ctypes.c_ulong),
        ("dwHighDateTime", ctypes.c_ulong),
    ]


def _get_system_times() -> tuple[int, int, int]:
    idle = _FileTime()
    kernel = _FileTime()
    user = _FileTime()
    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        raise OSError("GetSystemTimes failed")
    return _to_int(idle), _to_int(kernel), _to_int(user)


def _to_int(value: _FileTime) -> int:
    return (value.dwHighDateTime << 32) | value.dwLowDateTime


def cpu_busy_percent(sample_seconds: float = 0.75) -> float:
    start_idle, start_kernel, start_user = _get_system_times()
    time.sleep(max(sample_seconds, 0.05))
    end_idle, end_kernel, end_user = _get_system_times()

    idle_delta = end_idle - start_idle
    kernel_delta = end_kernel - start_kernel
    user_delta = end_user - start_user
    total_delta = kernel_delta + user_delta
    if total_delta <= 0:
        return 0.0

    busy_fraction = 1.0 - (idle_delta / total_delta)
    return max(0.0, min(100.0, busy_fraction * 100.0))


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free
