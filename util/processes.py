"""Liveness, identity, and termination of processes evolver spawned earlier.

The non-AI upscale stage hands a multi-hour encode to a detached ffmpeg and
finds it again on a later scheduler tick knowing only its pid.  ctypes keeps
this dependency-free; the identity check exists because a recycled pid must
never get another process killed in ffmpeg's name.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
from pathlib import Path

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_READ = 0x0010
_PROCESS_TERMINATE = 0x0001
_PROCESS_SUSPEND_RESUME = 0x0800
_STILL_ACTIVE = 259
_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_kernel32 = ctypes.windll.kernel32
_ntdll = ctypes.windll.ntdll


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.wintypes.DWORD),
        ("cntUsage", ctypes.wintypes.DWORD),
        ("th32ProcessID", ctypes.wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", ctypes.wintypes.DWORD),
        ("cntThreads", ctypes.wintypes.DWORD),
        ("th32ParentProcessID", ctypes.wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


class _PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p),
        ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2),
        ("UniqueProcessId", ctypes.c_void_p),
        ("Reserved3", ctypes.c_void_p),
    ]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", ctypes.c_ushort),
        ("MaximumLength", ctypes.c_ushort),
        ("Buffer", ctypes.c_void_p),
    ]


def pids_of_image(image: Path) -> list[int]:
    """Every live pid whose executable is exactly *image* (full-path match)."""
    target = str(image).lower()
    basename = image.name.lower()
    pids: list[int] = []
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
        return pids
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        if not _kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return pids
        while True:
            if entry.szExeFile.lower() == basename:
                full = image_path(entry.th32ProcessID)
                if full and full.lower() == target:
                    pids.append(entry.th32ProcessID)
            if not _kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                return pids
    finally:
        _kernel32.CloseHandle(snapshot)


def count_running(image: Path) -> int:
    return len(pids_of_image(image))


def command_line(pid: int) -> str | None:
    """The command line *pid* was started with, or None when unreadable.

    Reads the PEB's ProcessParameters (x64 offsets), the only dependency-free
    way to see another process's arguments on Windows.
    """
    handle = _kernel32.OpenProcess(
        _PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ, False, pid
    )
    if not handle:
        return None
    try:
        pbi = _PROCESS_BASIC_INFORMATION()
        if _ntdll.NtQueryInformationProcess(
            handle, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None
        ) != 0 or not pbi.PebBaseAddress:
            return None
        params_raw = _read_memory(handle, pbi.PebBaseAddress + 0x20, 8)
        if params_raw is None:
            return None
        params_ptr = ctypes.c_void_p.from_buffer_copy(params_raw).value
        if not params_ptr:
            return None
        ustr_raw = _read_memory(handle, params_ptr + 0x70, ctypes.sizeof(_UNICODE_STRING))
        if ustr_raw is None:
            return None
        ustr = _UNICODE_STRING.from_buffer_copy(ustr_raw)
        if not ustr.Buffer or not ustr.Length:
            return None
        raw = _read_memory(handle, ustr.Buffer, ustr.Length)
        if raw is None:
            return None
        return raw.decode("utf-16-le", errors="replace")
    finally:
        _kernel32.CloseHandle(handle)


def _read_memory(handle, address: int, size: int) -> bytes | None:
    buffer = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t()
    ok = _kernel32.ReadProcessMemory(
        handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(read)
    )
    return buffer.raw if ok else None


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


def suspend(pid: int) -> bool:
    """Freeze *pid* in place. True when the suspend call was accepted.

    Every thread stops; the process keeps its memory and (for an ffmpeg encode)
    its GPU context but burns zero CPU/GPU, so an in-flight upscale can be
    parked the moment the user returns and thawed later exactly where it left
    off — no lost hours, unlike killing it.
    """
    return _set_frozen(pid, _ntdll.NtSuspendProcess)


def resume(pid: int) -> bool:
    """Thaw a process suspended earlier. True when the resume call was accepted.

    Safe to call on a process that was never suspended (its suspend count is
    already zero), which lets an adopted orphan be unconditionally un-frozen.
    """
    return _set_frozen(pid, _ntdll.NtResumeProcess)


def _set_frozen(pid: int, nt_call) -> bool:
    handle = _kernel32.OpenProcess(_PROCESS_SUSPEND_RESUME, False, pid)
    if not handle:
        return False
    try:
        return nt_call(handle) == 0  # 0 == STATUS_SUCCESS
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
