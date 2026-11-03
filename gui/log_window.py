from __future__ import annotations

from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout


class RunLogWindow(QDialog):
    def __init__(self, title: str, text: str, note: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Evolver — Log for {title}")
        self.setMinimumSize(600, 300)
        self.resize(1000, 600)

        layout = QVBoxLayout(self)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._view.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._view.setPlaceholderText(note)
        self._view.setPlainText(text)
        layout.addWidget(self._view)
