from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout
from shared_ui.find_bar import FindBar


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

        self._find_bar = FindBar("Find:", "", dismiss_key="Esc")
        layout.addWidget(self._find_bar)
        QShortcut(QKeySequence.StandardKey.Find, self).activated.connect(
            partial(self._find_bar.open_find, [self._view]))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._find_bar.isVisible():
            self._find_bar.close_find()
            return
        super().keyPressEvent(event)
