"""The colors Windows would otherwise pick for this app."""

from __future__ import annotations

from PyQt6.QtGui import QPalette

from shared_ui.colors import BLUE, TEXT_PRIMARY


def apply_accent(app) -> None:
    """Put the family's blue where Qt would put the machine's accent color.

    Qt takes Link, Highlight and their kin from the Windows accent, so a box
    set to orange draws this app's links and selections orange -- a color that
    is in no palette any app of this family reads, sitting beside marks that
    are. The accent is a per-machine setting nobody chose for Evolver, and it
    changes under the app while it runs; the family's blue is the one this
    suite already spends on a control that is on.

    A visited link keeps that same blue on purpose. These links are not the
    web's -- a run title goes to that run's own lines and nowhere else -- so a
    second color would only say which titles had been clicked before.
    """
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Link, BLUE)
    palette.setColor(QPalette.ColorRole.LinkVisited, BLUE)
    palette.setColor(QPalette.ColorRole.Highlight, BLUE)
    # Black was legible on the pale orange Windows offered and is not on this;
    # the family's own brightest text is what a selected row wears instead.
    palette.setColor(QPalette.ColorRole.HighlightedText, TEXT_PRIMARY)
    app.setPalette(palette)
