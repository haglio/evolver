"""Vulture whitelist — false positives that are not dead code.

Each entry tells vulture the name is used, suppressing the report.
Only add names here that are *provably* called by a framework or
accessed dynamically at runtime.
"""
from __future__ import annotations

# -- Qt virtual-method overrides (called by the event loop) --
# mousePressEvent, mouseReleaseEvent and paintEvent are not here: each one's
# base implementation is called by name somewhere in the tree, so vulture
# already sees them used and an entry would suppress nothing.
_.drawFocus
# The drag-and-drop half of the same: Qt calls these on the widget the pointer
# is over, and startDrag when a row is picked up (gui/queue_window.py).
_.dropEvent
_.startDrag
# Qt hands every event of the application to a filter installed on it
# (gui/process_identity.py).
_.eventFilter

# -- Python HTMLParser overrides --
_.handle_starttag
_.handle_endtag
_.handle_startendtag
_.handle_data

# -- Win32 ctypes struct fields (consumed by C API, not Python) --
_.dwSize
_.dwLength

# -- Dataclass fields consumed via dataclasses.asdict() --
_.stopped_at_budget

# -- BackfillWindow's read surface: reached from the tests, which the vulture
#    scan deliberately excludes. The accessors exist so assertions about the
#    window go through a public seam instead of six private attributes. --
_.status_text
_.hearing_text
_.last_text
_.tile_for
