"""Vulture whitelist — false positives that are not dead code.

Each entry tells vulture the name is used, suppressing the report.
Only add names here that are *provably* called by a framework or
accessed dynamically at runtime.
"""

# -- Qt virtual-method overrides (called by the event loop) --
# mousePressEvent and mouseReleaseEvent are not here: each calls the other's
# base implementation for the events it declines, so vulture already sees them
# used and an entry would suppress nothing.
_.paintEvent  # noqa: F821
_.drawFocus  # noqa: F821
_.option  # noqa: F821  — drawFocus override parameter (Qt signature)

# -- Python HTMLParser overrides --
_.handle_starttag  # noqa: F821
_.handle_endtag  # noqa: F821
_.handle_startendtag  # noqa: F821
_.handle_data  # noqa: F821

# -- Win32 ctypes struct fields (consumed by C API, not Python) --
_.vt  # noqa: F821  — _PROPVARIANT.vt (VARTYPE tag)
_.pwszVal  # noqa: F821  — _PROPVARIANT.pwszVal (wide string value)
_.dwSize  # noqa: F821  — _PROCESSENTRY32W.dwSize (required by Process32FirstW)
_.dwLength  # noqa: F821  — _MemoryStatusEx.dwLength (required by GlobalMemoryStatusEx)
_.cbSize  # noqa: F821  — _LastInputInfo.cbSize (required by GetLastInputInfo)

# -- Dataclass fields consumed via dataclasses.asdict() --
_.timed_out  # noqa: F821  — UpscaleResult.timed_out, serialized to run records

# -- Written-but-never-read on purpose: the reference IS the job --
_._show_requests  # noqa: F821  — anchors the QLocalServer; collecting it closes the pipe

# -- BackfillWindow's read surface: reached from the tests, which the vulture
#    scan deliberately excludes. The accessors exist so assertions about the
#    window go through a public seam instead of six private attributes. --
_.status_text  # noqa: F821
_.hearing_text  # noqa: F821
_.last_text  # noqa: F821
_.tile_for  # noqa: F821
