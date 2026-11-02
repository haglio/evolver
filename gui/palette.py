"""The colors Windows would otherwise pick for this app."""

from __future__ import annotations

from PyQt6.QtGui import QPalette
from shared_ui.colors import BLUE, family_palette


def apply_accent(app) -> None:
    """The family's palette, but a visited link keeps the unvisited blue on purpose.

    These links are not the web's -- a run title goes to that run's own lines and
    nowhere else -- so a second color would only say which titles had been clicked
    before.
    """
    palette = family_palette(app.palette())
    palette.setColor(QPalette.ColorRole.LinkVisited, BLUE)
    app.setPalette(palette)
