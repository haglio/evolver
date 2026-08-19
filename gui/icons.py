"""Evolver's icons.

Most of the toolbar and the tray menu is still Font Awesome, which suits the
verbs nothing else in the family draws -- a cog for settings, a chart, a film
strip.  Three marks are not left to it, because the family draws them and the
apps sit open side by side:

* quit, the power symbol -- Fun Time paints this same one on its bar,
* restart, that power symbol with its ring running on into an arrowhead, so the
  two sit together in a menu as obvious relatives rather than as an unrelated
  pair (Font Awesome's "redo" is a plain circular arrow, which is what an undo
  looks like everywhere else here),
* run now, the play triangle, whose corners are rounded the way an icon font's
  transport controls are.
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


def quit_icon(color: str) -> QIcon:
    """The family's power mark -- and restart is built from its ring and stroke,
    so the two read as relatives where they sit beside each other."""
    return glyph_icon("power", color=color)


def run_now_icon(color: str) -> QIcon:
    """The family's play triangle, corners rounded like the transport marks it
    replaces."""
    return glyph_icon("play", color=color)
