"""Set Windows taskbar pin properties so the app pins as 'Evolver' with the pink E icon.

When a PyQt app runs via pythonw.exe, Windows associates pinned shortcuts with
Python rather than the app.  Setting IPropertyStore relaunch properties on the
window handle tells the taskbar the correct name, icon, and launch command.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import struct

from util.win32_loader import HRESULT, load_dll, win_functype

log = logging.getLogger(__name__)


def _guid_bytes(s: str) -> bytes:
    """Convert 'XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX' to 16-byte LE GUID."""
    p = s.split("-")
    return struct.pack("<IHH", int(p[0], 16), int(p[1], 16), int(p[2], 16)) + bytes.fromhex(p[3] + p[4])


class _GUID(ctypes.Structure):
    _fields_ = [("raw", ctypes.c_byte * 16)]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wt.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    """Minimal PROPVARIANT supporting only VT_LPWSTR (31)."""
    _fields_ = [
        ("vt", wt.USHORT),
        ("_pad", ctypes.c_byte * 6),
        ("pwszVal", ctypes.c_wchar_p),
    ]


_VT_LPWSTR = 31

# System.AppUserModel.* property keys — all share the same format GUID.
_AUMID_GUID = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"


def _pkey(pid: int) -> _PROPERTYKEY:
    pk = _PROPERTYKEY()
    ctypes.memmove(pk.fmtid.raw, _guid_bytes(_AUMID_GUID), 16)
    pk.pid = pid
    return pk


_PK_ID = _pkey(5)        # System.AppUserModel.ID
_PK_RELAUNCH = _pkey(2)  # System.AppUserModel.RelaunchCommand
_PK_ICON = _pkey(3)      # System.AppUserModel.RelaunchIconResource
_PK_DISPLAY = _pkey(4)   # System.AppUserModel.RelaunchDisplayNameResource

# IID_IPropertyStore = {886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}
_IID_IPS = _GUID()
ctypes.memmove(_IID_IPS.raw, _guid_bytes("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), 16)

# COM vtable indices: IUnknown(0,1,2), GetCount(3), GetAt(4), GetValue(5), SetValue(6), Commit(7)
_RELEASE = 2
_SETVALUE = 6
_COMMIT = 7

_SetValueType = win_functype(
    HRESULT, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT),
)
_CommitType = win_functype(HRESULT, ctypes.c_void_p)
_ReleaseType = win_functype(wt.ULONG, ctypes.c_void_p)

_SHGetPropertyStoreForWindow = load_dll("shell32").SHGetPropertyStoreForWindow
_SHGetPropertyStoreForWindow.argtypes = [wt.HWND, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
_SHGetPropertyStoreForWindow.restype = HRESULT


def set_taskbar_properties(hwnd: int, app_id: str, relaunch_cmd: str, display_name: str, icon_path: str) -> None:
    """Set AppUserModel properties on *hwnd* so pinning uses the correct icon/name.

    Errors are logged but never raised — taskbar cosmetics must not crash the app.
    """
    try:
        _set_properties(hwnd, app_id, relaunch_cmd, display_name, icon_path)
    except Exception:
        log.warning("Failed to set taskbar pin properties", exc_info=True)


def _vtable_method(obj_ptr: int, index: int, proto):
    """Fetch a COM vtable entry by *index* and cast to *proto*."""
    vtable_addr = ctypes.cast(obj_ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    func_addr = ctypes.cast(vtable_addr, ctypes.POINTER(ctypes.c_void_p))[index]
    return proto(func_addr)


def _set_properties(hwnd: int, app_id: str, relaunch_cmd: str, display_name: str, icon_path: str) -> None:
    ps = ctypes.c_void_p()
    hr = _SHGetPropertyStoreForWindow(hwnd, ctypes.byref(_IID_IPS), ctypes.byref(ps))
    if hr != 0:
        raise ctypes.WinError(hr)

    try:
        set_value = _vtable_method(ps.value, _SETVALUE, _SetValueType)
        for pkey, val in [
            (_PK_ID, app_id),
            (_PK_RELAUNCH, relaunch_cmd),
            (_PK_DISPLAY, display_name),
            (_PK_ICON, icon_path),
        ]:
            pv = _PROPVARIANT()
            pv.vt = _VT_LPWSTR
            pv.pwszVal = val
            hr = set_value(ps, ctypes.byref(pkey), ctypes.byref(pv))
            if hr != 0:
                raise ctypes.WinError(hr)

        commit = _vtable_method(ps.value, _COMMIT, _CommitType)
        hr = commit(ps)
        if hr != 0:
            raise ctypes.WinError(hr)
    finally:
        release = _vtable_method(ps.value, _RELEASE, _ReleaseType)
        release(ps)
