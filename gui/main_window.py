"""Main window with run history list and detail/progress panel."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import config
from gui.progress import STAGE_NUMBER, STAGE_TOOLTIPS, RunProgressWidget
from gui.run_record import RunRecord, load_runs


class RunDetailWidget(QWidget):
    """Shows details of a completed run."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._header = QLabel("Select a run to view details")
        font = self._header.font()
        font.setPointSize(font.pointSize() + 1)
        font.setBold(True)
        self._header.setFont(font)
        layout.addWidget(self._header)

        self._info_label = QLabel("")
        layout.addWidget(self._info_label)

        self._table = QTableWidget()
        self._table.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["#", "Stage", "Status", "Duration", "Details"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

    def show_record(self, record: RunRecord):
        self._header.setText(f"Run: {record.started_at}")
        status_text = "Success" if record.status == "success" else "Errors"
        self._info_label.setText(
            f"Trigger: {record.trigger}  |  Duration: {record.duration_seconds:.1f}s  |  Status: {status_text}"
        )

        self._table.setRowCount(len(record.stages))
        for i, stage in enumerate(record.stages):
            stage_key = stage.get("name", "")

            no_edit = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled

            # Column 0: stage number
            num = STAGE_NUMBER.get(stage_key, i + 1)
            num_item = QTableWidgetItem(str(num))
            num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            num_item.setForeground(QColor(0x80, 0x80, 0x80))
            num_item.setFlags(no_edit)
            self._table.setItem(i, 0, num_item)

            # Column 1: stage name with tooltip
            name_item = QTableWidgetItem(stage_key)
            name_item.setToolTip(STAGE_TOOLTIPS.get(stage_key, ""))
            name_item.setFlags(no_edit)
            self._table.setItem(i, 1, name_item)

            # Column 2: status
            status_item = QTableWidgetItem(stage.get("status", ""))
            status = stage.get("status", "")
            if status == "completed":
                status_item.setForeground(QColor(0x30, 0xA0, 0x30))
            elif status == "skipped":
                status_item.setForeground(QColor(0x80, 0x80, 0x80))
            elif status == "error":
                status_item.setForeground(QColor(0xE0, 0x30, 0x30))
            status_item.setFlags(no_edit)
            self._table.setItem(i, 2, status_item)

            # Column 3: duration
            duration = stage.get("duration_seconds", 0.0)
            dur_item = QTableWidgetItem(f"{duration:.1f}s")
            dur_item.setFlags(no_edit)
            self._table.setItem(i, 3, dur_item)

            # Column 4: details (double-click to select/copy text)
            details = _summarize_result(stage.get("result"), stage.get("skip_reason"))
            details_item = QTableWidgetItem(details)
            self._table.setItem(i, 4, details_item)

    def clear(self):
        self._header.setText("Select a run to view details")
        self._info_label.setText("")
        self._table.setRowCount(0)


def _summarize_result(result: dict[str, Any] | None, skip_reason: str | None = None) -> str:
    """Build a short summary string from a stage result dict."""
    if skip_reason:
        return f"Reason: {skip_reason}"
    if not result:
        return ""
    # Pick interesting non-zero numeric fields
    parts = []
    for key, value in result.items():
        if isinstance(value, (int, float)) and value and not key.startswith("_"):
            parts.append(f"{key}={value}")
    return ", ".join(parts[:5])


class EvolverMainWindow(QMainWindow):
    """Main window: run history list on the left, detail/progress on the right."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Evolver")
        self.setMinimumSize(800, 500)
        self.resize(1000, 600)
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        # Left panel: run history
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 4, 8)

        history_header = QLabel("Run History")
        font = history_header.font()
        font.setBold(True)
        history_header.setFont(font)
        left_layout.addWidget(history_header)

        self._history_list = QListWidget()
        self._history_list.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._history_list.currentRowChanged.connect(self._on_history_selection)
        left_layout.addWidget(self._history_list)
        splitter.addWidget(left)

        # Right panel: stacked (detail view / progress view)
        self._stack = QStackedWidget()
        self._detail_widget = RunDetailWidget()
        self._progress_widget = RunProgressWidget()
        self._stack.addWidget(self._detail_widget)   # index 0
        self._stack.addWidget(self._progress_widget)  # index 1
        splitter.addWidget(self._stack)

        splitter.setSizes([300, 700])

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_label = QLabel("Starting...")
        self._status_bar.addWidget(self._status_label)

        self._records: list[RunRecord] = []

    @property
    def progress_widget(self) -> RunProgressWidget:
        return self._progress_widget

    def show_progress(self):
        """Switch the right panel to show live progress."""
        self._progress_widget.reset()
        self._stack.setCurrentIndex(1)
        # Add a "Running..." entry at the top of the history list
        item = QListWidgetItem("\u25B6  Running...")
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setForeground(QColor(0x30, 0x80, 0xE0))
        self._history_list.insertItem(0, item)
        self._history_list.setCurrentRow(0)

    def finish_progress(self):
        """Remove the 'Running...' entry and switch back to detail view."""
        if self._history_list.count() > 0:
            first = self._history_list.item(0)
            if first and first.text().startswith("\u25B6"):
                self._history_list.takeItem(0)
        self._stack.setCurrentIndex(0)

    def refresh_history(self):
        """Reload run records from disk."""
        self._records = load_runs(config.RUNS_DIR)
        self._history_list.clear()
        for record in self._records:
            status_icon = "\u2714" if record.status == "success" else "\u2718"
            text = f"{status_icon}  {record.started_at}  ({record.duration_seconds:.0f}s)"
            item = QListWidgetItem(text)
            if record.status != "success":
                item.setForeground(QColor(0xE0, 0x30, 0x30))
            self._history_list.addItem(item)

        if self._records:
            self._history_list.setCurrentRow(0)

    def _on_history_selection(self, row: int):
        if 0 <= row < len(self._records):
            self._detail_widget.show_record(self._records[row])
            self._stack.setCurrentIndex(0)

    def update_schedule_status(self, is_running: bool, is_paused: bool, next_run_at: datetime | None):
        """Update the status bar with current scheduling state."""
        if is_running:
            self._status_label.setText("Status: Running...")
        elif is_paused:
            self._status_label.setText("Status: Scheduling paused")
        elif next_run_at:
            self._status_label.setText(f"Status: Scheduled  |  Next run: {next_run_at.strftime('%H:%M')}")
        else:
            self._status_label.setText("Status: Idle")

    def closeEvent(self, event):
        """Hide instead of close — the tray icon keeps the app alive."""
        event.ignore()
        self.hide()
