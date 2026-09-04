"""Main window with run history list and detail/progress panel."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import qtawesome as qta
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction
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
from shared_ui.spacing import BUTTON_ICON

import config
from gui.icons import quit_icon, restart_icon, run_now_icon
from gui.run_record import RunRecord, format_run_label, load_runs
from gui.status_symbols import GRAY, mark_for, mark_icon
from gui.toggle_switch import ToggleSwitch
from tasks.stages import STAGE_LABELS, STAGE_NUMBER, STAGE_TOOLTIPS

_ICON_COLOR = "#ddd"


class _NoFocusRectDelegate(QItemDelegate):
    """QItemDelegate subclass that suppresses the focus rectangle.

    Uses QItemDelegate (not QStyledItemDelegate) because QItemDelegate
    exposes drawFocus() as a dedicated override point for this purpose.
    """

    def drawFocus(self, painter, option, rect):
        pass  # Don't draw the focus rectangle


class RunDetailWidget(QWidget):
    """Shows details of a completed run."""

    # The run whose log to show. What the stage table holds is a summary of
    # each stage's counters; the words the stages actually wrote -- which file,
    # which error -- only ever existed in the log, and this is the way there.
    log_requested = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._record: RunRecord | None = None

        self._header = QLabel("Select a run to view details")
        font = self._header.font()
        font.setPointSize(font.pointSize() + 1)
        font.setBold(True)
        self._header.setFont(font)
        # The title carries an <a href> once a run is in hand, so the format is
        # stated rather than guessed at from the string -- the same reason the
        # info line below sets it.
        self._header.setTextFormat(Qt.TextFormat.RichText)
        self._header.linkActivated.connect(self._on_title_clicked)
        layout.addWidget(self._header)

        self._info_label = QLabel("")
        # Explicit, not AutoText: the run's mark is a colored <span>, and
        # leaving the format to Qt's guess-from-the-string heuristic risks the
        # line being drawn as literal markup.
        self._info_label.setTextFormat(Qt.TextFormat.RichText)
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
        self._record = record
        # No color of its own: the link wears the palette's, so it reads as a
        # link in whichever theme Qt has given the rest of the window.
        self._header.setText(f'<a href="log">Run: {record.started_at}</a>')
        self._header.setToolTip("Show what this run wrote to the log")
        glyph, color = mark_for(record.status)
        # Rich text so the mark alone is colored; the rest of the line stays
        # the label's own color, matching the history list beside it.
        self._info_label.setText(
            f"Trigger: {record.trigger}  |  Duration: {record.duration_seconds:.1f}s"
            f'  |  Status: <span style="color: {color.name()}">{glyph}</span>'
        )
        self._info_label.setToolTip(record.status)

        self._table.setRowCount(len(record.stages))
        for i, stage in enumerate(record.stages):
            stage_key = stage.get("name", "")

            no_edit = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled

            # A record can name a stage this build no longer has — regeneration
            # mode was one — and its position in a run is not its position in
            # the pipeline. Guessing an ordinal there is what let a stage with
            # no registry row take the number of the stage after it.
            num = STAGE_NUMBER.get(stage_key)
            num_item = QTableWidgetItem("\u2014" if num is None else str(num))
            num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            num_item.setForeground(GRAY)
            num_item.setFlags(no_edit)
            self._table.setItem(i, 0, num_item)

            name_item = QTableWidgetItem(STAGE_LABELS.get(stage_key, stage_key))
            name_item.setToolTip(STAGE_TOOLTIPS.get(stage_key, ""))
            name_item.setFlags(no_edit)
            self._table.setItem(i, 1, name_item)

            # Column 2: status, as its symbol — the word is the tooltip, so the
            # color lands on a glyph rather than on a block of text.
            status = stage.get("status", "")
            glyph, color = mark_for(status)
            status_item = QTableWidgetItem(glyph)
            status_item.setForeground(color)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setToolTip(status)
            status_item.setFlags(no_edit)
            self._table.setItem(i, 2, status_item)

            duration = stage.get("duration_seconds", 0.0)
            dur_item = QTableWidgetItem(f"{duration:.1f}s")
            dur_item.setFlags(no_edit)
            self._table.setItem(i, 3, dur_item)

            details = _summarize_result(stage.get("result"), stage.get("skip_reason"), stage_key)
            details_item = QTableWidgetItem(details)
            self._table.setItem(i, 4, details_item)

    def clear(self):
        self._record = None
        self._header.setText("Select a run to view details")
        self._header.setToolTip("")
        self._info_label.setText("")
        self._table.setRowCount(0)

    def _on_title_clicked(self, _href: str):
        if self._record is not None:
            self.log_requested.emit(self._record)


# Fields always shown for a stage even when zero, so "0 succeeded" stays visible
# instead of vanishing and making a total failure look like a partial one.
_HEADLINE_FIELDS = {
    "metadata": ("newly_scraped", "errors"),
}


def _summarize_result(
    result: dict[str, Any] | None,
    skip_reason: str | None = None,
    stage_key: str = "",
) -> str:
    """Build a short summary string from a stage result dict."""
    if skip_reason:
        return f"Reason: {skip_reason}"
    if not result:
        return ""
    custom = _SUMMARIZERS.get(stage_key)
    if custom is not None:
        return custom(result)
    headline = _HEADLINE_FIELDS.get(stage_key, ())
    parts = [f"{key}={result[key]}" for key in headline
             if isinstance(result.get(key), (int, float))]
    # Then any other interesting non-zero numeric fields.
    for key, value in result.items():
        if key in headline:
            continue
        if isinstance(value, (int, float)) and value and not key.startswith("_"):
            parts.append(f"{key}={value}")
    return ", ".join(parts[:5])


# What each scripts-sync counter means, in words. The first group is what makes
# the stage red; the second is the work it got done.
_SCRIPTS_PROBLEMS = (
    ("unmatched", "match no video"),
    ("ambiguous", "match more than one video"),
    ("collisions", "cannot move — a different script holds the destination"),
    ("variant_copy_errors", "failed to copy to a variant"),
)
_SCRIPTS_ROUTINE = (
    ("moved", "moved into place"),
    ("copied_variants", "copied to a variant"),
    ("followed_to_archive", "followed a retired video out of the library"),
    ("discarded_duplicates", "duplicate discarded"),
    ("already_aligned", "already aligned"),
)
_SCRIPTS_NAMES_SHOWN = 3


def _summarize_scripts_sync(result: dict[str, Any]) -> str:
    """Say what made this stage red, in words, and name the scripts at fault.

    The generic numeric dump lists the counters in dataclass order and keeps the
    first five, which read as bland tallies — an "unmatched=15" sitting beside
    an "already_aligned=53" with nothing marking which one is the failure, and a
    counter as late as variant_copy_errors dropped off the line entirely.
    Naming the offending scripts is the difference between knowing the stage
    failed and knowing what to go fix.
    """
    problems = [f"{result[key]} {label}" for key, label in _SCRIPTS_PROBLEMS
                if isinstance(result.get(key), int) and result[key]]
    if not problems:
        routine = [f"{result[key]} {label}" for key, label in _SCRIPTS_ROUTINE
                   if isinstance(result.get(key), int) and result[key]]
        return ", ".join(routine) if routine else "no funscripts"

    summary = "; ".join(problems)
    names = result.get("unmatched_paths") or []
    if names:
        summary += f" — {_name_sample(names)}"
    return summary


def _name_sample(names: list[str]) -> str:
    """The first few names, with a count standing in for the rest."""
    shown = ", ".join(names[:_SCRIPTS_NAMES_SHOWN])
    remainder = len(names) - _SCRIPTS_NAMES_SHOWN
    return f"{shown} +{remainder} more" if remainder > 0 else shown


def _summarize_nonai_upscale(result: dict[str, Any]) -> str:
    """Say which non-AI clip is in hand and what just happened to it.

    This stage reports its outcomes as clip names — strings the generic numeric
    dump drops entirely, leaving a bare "suspended=True" and no way to tell
    which video was encoding or why its percent vanished between runs. Several
    of these can land on one tick (an encode finishes, then the next start is
    held back), so they read as a list rather than a single verdict.
    """
    parts = []
    if result.get("started"):
        parts.append(f"started {result['started']}")
    if result.get("in_flight"):
        parts.append(f"encoding {result['in_flight']} ({_encode_state(result)})")
    if result.get("promoted"):
        parts.append(f"finished {result['promoted']}")
    if result.get("stopped"):
        parts.append(f"stopped {result['stopped']} (still queued)")
    if result.get("failed"):
        parts.append(f"failed {result['failed']}")
    if result.get("deferred_low_disk"):
        parts.append("held back: low disk")
    elif result.get("start_deferred") and not result.get("in_flight"):
        parts.append(f"waiting ({result['start_deferred']})")
    parts.append(_whats_left(result))
    return ", ".join(parts)


def _whats_left(result: dict[str, Any]) -> str:
    """What is left of the project: clips, running time, and how far along.

    A clip count on its own says very little here. The queue runs from forty
    seconds to an hour a clip, and the short ones went first, so the library
    was 59% upscaled by clip and 29% by running time on the day this was
    written — the count moves twice as fast as the work does. The percentage is
    what moves at a rate worth reading, and the hours are what a person plans
    around.
    """
    left = f"{result.get('pending', 0)} queued"
    percent = result.get("percent_complete")
    if percent is None:
        # Nothing in the library has a running time recorded yet (the video
        # kinds stage writes them, a batch a run), so there is no percentage to
        # give and the count is all there is.
        return left
    hours = (result.get("remaining_seconds") or 0.0) / 3600
    unmeasured = result.get("unmeasured_videos") or 0
    missing = f", {unmeasured} not yet measured" if unmeasured else ""
    return f"{left} ({hours:.1f}h left, {percent}% done{missing})"


def _encode_state(result: dict[str, Any]) -> str:
    """How far the in-flight encode has gotten, and whether it is frozen."""
    percent = result.get("in_flight_percent")
    state = "progress unknown" if percent is None else f"{percent}%"
    if result.get("suspended"):
        state += ", paused: you're at the machine"
    return state


class EvolverMainWindow(QMainWindow):
    """Main window: run history list on the left, detail/progress on the right."""

    # Passed straight out of the detail pane. The app owns every window this
    # one opens beside it, the stats window included, so the view asks rather
    # than opens.
    log_requested = pyqtSignal(object)

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

        self._detail_widget = RunDetailWidget()
        self._detail_widget.log_requested.connect(self.log_requested)
        splitter.addWidget(self._detail_widget)

        splitter.setSizes([300, 700])

        self._records: list[RunRecord] = []

    def _build_toolbar(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        # The family's icon size, so a mark here is the size a mark in any
        # other app's row of buttons is.
        toolbar.setIconSize(QSize(BUTTON_ICON, BUTTON_ICON))
        self.addToolBar(toolbar)

        left_pad = QWidget()
        left_pad.setFixedWidth(6)
        toolbar.addWidget(left_pad)

        self.active_toggle = ToggleSwitch(checked=True)
        toolbar.addWidget(self.active_toggle)

        toolbar.addSeparator()

        self._next_run_label = QLabel("")
        toolbar.addWidget(self._next_run_label)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self.run_now_action = QAction(run_now_icon(_ICON_COLOR), "Run Now", self)
        toolbar.addAction(self.run_now_action)

        toolbar.addSeparator()

        self.settings_action = QAction(qta.icon("fa5s.cog", color=_ICON_COLOR), "Settings", self)
        toolbar.addAction(self.settings_action)

        self.stats_action = QAction(qta.icon("fa5s.chart-bar", color=_ICON_COLOR), "Stats", self)
        toolbar.addAction(self.stats_action)

        self.restart_action = QAction(restart_icon(_ICON_COLOR), "Restart", self)
        toolbar.addAction(self.restart_action)

        self.quit_action = QAction(quit_icon(_ICON_COLOR), "Quit", self)
        toolbar.addAction(self.quit_action)

    def commands(self):
        """Each toolbar command's signal, by the name the app knows it as.

        The same names the tray menu uses, so a command the two share is
        connected once on each side rather than spelled out twice in the app.
        Quit is the one that differs in what it does: from here it asks first.
        """
        return {
            "run_now": self.run_now_action.triggered,
            "pause": self.active_toggle.clicked,
            "settings": self.settings_action.triggered,
            "stats": self.stats_action.triggered,
            "restart": self.restart_action.triggered,
            "quit": self.quit_action.triggered,
        }

    def refresh_history(self):
        """Reload run records from disk."""
        self._records = load_runs(config.RUNS_DIR, limit=config.RUNS_SHOWN)
        self._history_list.clear()
        for record in self._records:
            item = QListWidgetItem(
                mark_icon(record.status),
                format_run_label(record.started_at, record.duration_seconds),
            )
            item.setToolTip(record.status)
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


# The two stages whose results are names and words rather than counts, so the
# generic numeric dump has nothing useful to say about them. A table rather
# than two `stage_key ==` branches, so a key that stops naming a stage is
# something a test can see (tests/test_stage_registry.py).
_SUMMARIZERS = {
    "upscale_non_ai": _summarize_nonai_upscale,
    "scripts": _summarize_scripts_sync,
}
