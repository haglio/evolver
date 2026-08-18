"""Evolver's icons.

Nearly everything on the toolbar and in the tray menu is a Font Awesome glyph,
which suits the ordinary verbs -- play, pause, a cog for settings.  Restart is
not ordinary: it is the one control that takes the whole app down and brings it
back, and Font Awesome's "redo" is a plain circular arrow, which is what an undo
looks like everywhere else in this family.

So that one comes out of :mod:`shared_ui.icons` -- a power symbol whose ring
runs on into an arrowhead -- and it is the same mark wherever the family offers
the same act.
"""

from __future__ import annotations

from PyQt6.QtGui import QIcon

from shared_ui.icons import glyph_icon


def restart_icon(color: str) -> QIcon:
    """The family's restart mark, tinted for the chrome it sits on.

    The toolbar is dark and the tray menu is light, so the two callers pass
    different inks for the same drawing.
    """
    return glyph_icon("restart", color=color)
