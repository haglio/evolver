"""A window onto the stretch of the log one run wrote."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout


class RunLogWindow(QDialog):
    """Non-modal dialog showing one run's lines of the log.

    The run's stretch rather than the file: evolver's log is one appending file
    nothing rotates, hundreds of megabytes of it, and putting that in a widget
    is not something a window recovers from. The excerpt is cut before it gets
    here (:mod:`util.log_excerpt`); this only shows it.
    """

    def __init__(self, title: str, text: str, log_path: Path, parent=None):
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
        # Shown only when the excerpt is empty, which is a real outcome: the
        # log does not reach back to every run the history still lists. Saying
        # which file was looked in is the difference between "no log here" and
        # "the app is broken".
        self._view.setPlaceholderText(
            f"Nothing in {log_path} was written while this run ran.")
        self._view.setPlainText(text)
        layout.addWidget(self._view)
