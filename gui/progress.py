"""Live progress widget showing pipeline stage status."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

STAGES = [
    ("sort",      "Sort Inbox",           "Move videos from 0_inbox into 1_sorted by source and orientation"),
    ("purge",     "Purge Weird",          "Delete kinda_weird outputs and their matching sources in 1_sorted"),
    ("scripts",   "Scripts Sync",         "Align funscripts to mirror the video library tree"),
    ("bookmarks", "Bookmarks Sync",       "Sync Fun Time favorites into a Chrome bookmarks folder"),
    ("metadata",  "Metadata Scrape",      "Scrape AI prompt metadata into mirrored JSON files"),
    ("upscale",   "Upscale",              "Apply Topaz frame interpolation + 4x upscale to sorted videos"),
    ("dupes",     "Duplicate Check",      "Scan non_AI for likely duplicate videos by exact filesize"),
    ("verify",    "Correspondence Check", "Verify 1_sorted and 2_outbox are in 1-to-1 correspondence"),
]

ALL_STAGES = [key for key, _, _ in STAGES]
STAGE_DISPLAY_NAMES = {key: name for key, name, _ in STAGES}
STAGE_TOOLTIPS = {key: tip for key, _, tip in STAGES}
STAGE_NUMBER = {key: i + 1 for i, (key, _, _) in enumerate(STAGES)}


class StageRow(QFrame):
    """A single row showing one stage's status."""

    def __init__(self, stage_key: str, parent=None):
        super().__init__(parent)
        self._stage_key = stage_key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._number_label = QLabel(str(STAGE_NUMBER.get(stage_key, "")))
        self._number_label.setFixedWidth(20)
        self._number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._number_label.setStyleSheet("color: gray;")
        layout.addWidget(self._number_label)

        self._icon_label = QLabel("\u2022")  # bullet
        self._icon_label.setFixedWidth(20)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        self._name_label = QLabel(STAGE_DISPLAY_NAMES.get(stage_key, stage_key))
        self._name_label.setFixedWidth(160)
        self._name_label.setToolTip(STAGE_TOOLTIPS.get(stage_key, ""))
        layout.addWidget(self._name_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setVisible(False)
        self._progress.setFixedHeight(16)
        layout.addWidget(self._progress, stretch=1)

        self._status_label = QLabel("")
        self._status_label.setFixedWidth(100)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._status_label)

        self.set_pending()

    def set_pending(self):
        self._icon_label.setText("\u2022")
        self._icon_label.setStyleSheet("color: gray;")
        self._progress.setVisible(False)
        self._status_label.setText("")

    def set_running(self):
        self._icon_label.setText("\u25B6")  # play triangle
        self._icon_label.setStyleSheet("color: #3080E0;")
        self._progress.setVisible(True)
        self._status_label.setText("Running...")

    def set_completed(self, elapsed: float):
        self._icon_label.setText("\u2714")  # check mark
        self._icon_label.setStyleSheet("color: #30A030;")
        self._progress.setVisible(False)
        self._status_label.setText(f"{elapsed:.1f}s")

    def set_skipped(self, reason: str = ""):
        self._icon_label.setText("\u2014")  # em dash
        self._icon_label.setStyleSheet("color: gray;")
        self._progress.setVisible(False)
        self._status_label.setText("Skipped")

    def set_error(self, elapsed: float):
        self._icon_label.setText("\u2718")  # X mark
        self._icon_label.setStyleSheet("color: #E03030;")
        self._progress.setVisible(False)
        self._status_label.setText(f"Error ({elapsed:.1f}s)")


class RunProgressWidget(QWidget):
    """Shows all pipeline stages with live progress indicators."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        header = QLabel("Pipeline Progress")
        font = header.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        header.setFont(font)
        layout.addWidget(header)

        self._rows: dict[str, StageRow] = {}
        for stage_key in ALL_STAGES:
            row = StageRow(stage_key)
            self._rows[stage_key] = row
            layout.addWidget(row)

        layout.addStretch()

    def reset(self):
        for row in self._rows.values():
            row.set_pending()

    def on_stage_started(self, name: str):
        if name in self._rows:
            self._rows[name].set_running()

    def on_stage_completed(self, name: str, result: object, elapsed: float, status: str):
        if name not in self._rows:
            return
        if status == "completed":
            self._rows[name].set_completed(elapsed)
        elif status == "skipped":
            self._rows[name].set_skipped()
        elif status == "error":
            self._rows[name].set_error(elapsed)
