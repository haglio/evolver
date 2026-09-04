"""A window onto the stretch of the log one run wrote."""

from __future__ import annotations

from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout


class RunLogWindow(QDialog):
    """Non-modal dialog showing one run's lines of the log.

    The run's stretch rather than the file: evolver's log is one appending file
    nothing rotates, hundreds of megabytes of it, and putting that in a widget
    is not something a window recovers from. The lines are cut out before they
    get here (:mod:`util.run_log`); this only shows them, and shows *note* in
    their place when the run's mark led nowhere.
    """

    def __init__(self, title: str, text: str, note: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Evolver — Log for {title}")
        self.setMinimumSize(600, 300)
        self.resize(1000, 600)

        layout = QVBoxLayout(self)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        # Log lines carry full paths and run long. Wrapped, a stage's own line
        # becomes three and the column of timestamps that makes the file
        # readable stops lining up, so they scroll sideways instead.
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._view.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        # Shown only when there is nothing to show, which is a real outcome:
        # the history outlives the log, and runs older than the mark cannot be
        # pointed at in it at all. Saying which of those it was is the
        # difference between an explanation and a window that looks broken.
        self._view.setPlaceholderText(note)
        self._view.setPlainText(text)
        layout.addWidget(self._view)
