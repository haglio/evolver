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


def cpu_busy_percent(sample_seconds: float) -> float:
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


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def available_ram_gb() -> float:
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return status.ullAvailPhys / (1024 ** 3)


class _LastInputInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_ulong),
    ]


def seconds_since_last_input() -> float:
    """Seconds since the session's last keyboard or mouse input.

    The single presence signal the idle-upscale throttle needs: a long value
    means the user has stepped away (run harder), a short one means they are at
    the machine (back off). dwTime is a 32-bit GetTickCount stamp, so the
    difference is taken in 32-bit space to survive the ~49.7-day wrap.
    """
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(_LastInputInfo)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError("GetLastInputInfo failed")
    now_ticks = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    elapsed_ms = (now_ticks - info.dwTime) & 0xFFFFFFFF
    return elapsed_ms / 1000.0
