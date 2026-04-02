"""Main window with run history list and detail/progress panel."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QItemDelegate,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


class _NoFocusRectDelegate(QItemDelegate):
    """QItemDelegate subclass that suppresses the focus rectangle.

    Uses QItemDelegate (not QStyledItemDelegate) because QItemDelegate
    exposes drawFocus() as a dedicated override point for this purpose.
    """

    def drawFocus(self, painter, option, rect):
        pass  # Don't draw the focus rectangle


import qtawesome as qta

import config
from gui.progress import STAGE_NUMBER, STAGE_TOOLTIPS
from gui.run_record import RunRecord, load_runs, format_run_label
from gui.toggle_switch import ToggleSwitch
from shared_ui.colors import GREEN, RED, STATUS_NUMBER, STATUS_SKIP

_ICON_COLOR = "#ddd"


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
        self._table.setItemDelegate(_NoFocusRectDelegate(self._table))
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["#", "Stage", "Status", "Duration", "Details"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
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
            num_item.setForeground(STATUS_NUMBER)
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
                status_item.setForeground(GREEN)
            elif status == "skipped":
                status_item.setForeground(STATUS_SKIP)
            elif status == "error":
                status_item.setForeground(RED)
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

        self._build_toolbar()

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
        self._history_list.setItemDelegate(_NoFocusRectDelegate(self._history_list))
        self._history_list.currentRowChanged.connect(self._on_history_selection)
        left_layout.addWidget(self._history_list)
        splitter.addWidget(left)

        # Right panel: run detail view
        self._detail_widget = RunDetailWidget()
        splitter.addWidget(self._detail_widget)

        splitter.setSizes([300, 700])

        self._records: list[RunRecord] = []

    def _build_toolbar(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        # Small left pad so the toggle isn't flush with the window edge
        left_pad = QWidget()
        left_pad.setFixedWidth(6)
        toolbar.addWidget(left_pad)

        # Active/Paused toggle switch
        self.active_toggle = ToggleSwitch(checked=True)
        toolbar.addWidget(self.active_toggle)

        toolbar.addSeparator()

        # Next-run info label
        self._next_run_label = QLabel("")
        toolbar.addWidget(self._next_run_label)

        # Spacer pushes remaining actions to the right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        # Run Now
        self.run_now_action = QAction(qta.icon("fa5s.play", color=_ICON_COLOR), "Run Now", self)
        toolbar.addAction(self.run_now_action)

        toolbar.addSeparator()

        # Settings
        self.settings_action = QAction(qta.icon("fa5s.cog", color=_ICON_COLOR), "Settings", self)
        toolbar.addAction(self.settings_action)

        # Stats
        self.stats_action = QAction(qta.icon("fa5s.chart-bar", color=_ICON_COLOR), "Stats", self)
        toolbar.addAction(self.stats_action)

        # Restart
        self.restart_action = QAction(qta.icon("fa5s.redo", color=_ICON_COLOR), "Restart", self)
        toolbar.addAction(self.restart_action)

        # Quit
        self.quit_action = QAction(qta.icon("fa5s.power-off", color=_ICON_COLOR), "Quit", self)
        toolbar.addAction(self.quit_action)

    def refresh_history(self):
        """Reload run records from disk."""
        self._records = load_runs(config.RUNS_DIR)
        self._history_list.clear()
        for record in self._records:
            text = format_run_label(record.started_at, record.duration_seconds, record.status)
            item = QListWidgetItem(text)
            if record.status != "success":
                item.setForeground(RED)
            self._history_list.addItem(item)

        if self._records:
            self._history_list.setCurrentRow(0)

    def _on_history_selection(self, row: int):
        if 0 <= row < len(self._records):
            self._detail_widget.show_record(self._records[row])

    def update_schedule_status(self, is_running: bool, is_paused: bool, next_run_at: datetime | None):
        """Update toolbar controls with current scheduling state."""
        self.run_now_action.setEnabled(not is_running)
        self.active_toggle.setChecked(not is_paused)

        if is_paused:
            self._next_run_label.setText("No upcoming runs scheduled (inactive)")
        elif is_running:
            self._next_run_label.setText("Running...")
        elif next_run_at:
            self._next_run_label.setText(f"Next run: {next_run_at.strftime('%H:%M')}")
        else:
            self._next_run_label.setText("")

    def closeEvent(self, event):
        """Hide instead of close — the tray icon keeps the app alive."""
        event.ignore()
        self.hide()
