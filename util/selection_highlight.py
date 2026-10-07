from __future__ import annotations

from shared_ui.palette import BLUE, TEXT_PRIMARY, as_hex

# Windows 11's own look marks a picked row with a fill a shade off the ground,
# and on a dark desktop several picked rows read as none. The family's blue
# instead, the one Fun Time's library browser marks a picked video with.
SELECTION_HIGHLIGHT = (f"QAbstractItemView::item:selected {{ background-color: {as_hex(BLUE)};"
                       f" color: {as_hex(TEXT_PRIMARY)}; }}")
