"""Liveness, identity, and termination of processes evolver spawned earlier.

The non-AI upscale stage hands a multi-hour encode to a detached ffmpeg and
finds it again on a later scheduler tick knowing only its pid.  ctypes keeps
this dependency-free; the identity check exists because a recycled pid must
never get another process killed in ffmpeg's name.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_TERMINATE = 0x0001
_STILL_ACTIVE = 259

_kernel32 = ctypes.windll.kernel32


def image_path(pid: int) -> str | None:
    """The executable path behind *pid*, or None when it cannot be read."""
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = ctypes.wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        _kernel32.CloseHandle(handle)


def terminate(pid: int) -> bool:
    """Forcibly end *pid*. True when the terminate call was accepted."""
    handle = _kernel32.OpenProcess(_PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(_kernel32.TerminateProcess(handle, 1))
    finally:
        _kernel32.CloseHandle(handle)


def is_running(pid: int) -> bool:
    """Whether *pid* names a live process (a pid that exited 259 reads as live)."""
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == _STILL_ACTIVE
    finally:
        _kernel32.CloseHandle(handle)
