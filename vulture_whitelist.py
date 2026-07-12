"""Vulture whitelist — false positives that are not dead code.

Each entry tells vulture the name is used, suppressing the report.
Only add names here that are *provably* called by a framework or
accessed dynamically at runtime.
"""

# -- Qt virtual-method overrides (called by the event loop) --
_.paintEvent  # noqa: F821
_.mousePressEvent  # noqa: F821
_.closeEvent  # noqa: F821
_.sizeHint  # noqa: F821
_.drawFocus  # noqa: F821
_.accept  # noqa: F821  — QDialog.accept
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

# -- Dataclass fields consumed via dataclasses.asdict() --
_.timed_out  # noqa: F821  — UpscaleResult.timed_out, serialized to run records

# -- Script entry points (invoked by __main__ guard) --
_.main  # noqa: F821
