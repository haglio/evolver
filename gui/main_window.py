from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QBrush, QIcon, QPalette, QTextDocument
from PySide6.QtWidgets import (
    QHeaderView,
    QItemDelegate,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shared_ui import colors
from shared_ui.chrome import toolbar_rules
from shared_ui.code_text import as_rich_text
from shared_ui.flow_layout import FlowLayout
from shared_ui.icons import inline_icon
from shared_ui.spacing import (
    BUTTON_GAP,
    BUTTON_GROUP_GAP,
    BUTTON_ROW_GAP,
    GAP_DIALOG,
    GAP_SMALL,
    MARGIN_STANDARD,
)
from shared_ui.toggle_switch import ToggleSwitch

import config
from evolver import STAGE_NUMBER, STAGE_SECTION, STAGE_TOOLTIPS, stage_label
from gui.commands import (
    NONAI,
    PAUSE,
    QUEUE,
    QUIT,
    RESTART,
    REVIEW_TRASH,
    RUN_NOW,
    SETTINGS,
    STATS,
    pause_or_resume,
    set_label,
)
from gui.run_record import RunRecord, format_run_label, format_run_start, newest_runs
from gui.schedule_state import ScheduleStatus
from gui.stage_details import details_of
from gui.status_symbols import GRAY, status_icon, symbol_for
from gui.switches import SwitchButton, toolbar_button

_TEXT_INSET = GAP_SMALL


class _NoFocusRectDelegate(QItemDelegate):
    # QItemDelegate, not QStyledItemDelegate: only it exposes drawFocus().

    def drawFocus(self, painter, option, rect):
        pass

    def paint(self, painter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if isinstance(text, str) and "`" in text:
            self._paint_with_code(painter, option, index, text)
            return
        mark = index.data(Qt.ItemDataRole.DecorationRole)
        if index.data(Qt.ItemDataRole.DisplayRole) or not isinstance(mark, QIcon) or mark.isNull():
            super().paint(painter, option, index)
            return
        self.drawBackground(painter, option, index)
        pixmap = mark.pixmap(option.decorationSize)
        painter.drawPixmap(QStyle.alignedRect(option.direction, Qt.AlignmentFlag.AlignCenter,
                                              pixmap.deviceIndependentSize().toSize(), option.rect),
                           pixmap)

    def _paint_with_code(self, painter, option, index, text: str):
        self.drawBackground(painter, option, index)
        document = details_document(text, option.font)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette.setColor(QPalette.ColorRole.Text, option.palette.color(role))
        inset = (option.rect.height() - document.size().height()) / 2
        painter.save()
        painter.translate(option.rect.left() + _TEXT_INSET, option.rect.top() + inset)
        painter.setClipRect(0, 0, option.rect.width() - _TEXT_INSET, option.rect.height())
        document.documentLayout().draw(painter, context)
        painter.restore()


def details_document(text: str, font) -> QTextDocument:
    document = QTextDocument()
    document.setDefaultFont(font)
    document.setDocumentMargin(0)
    document.setHtml(as_rich_text(text))
    return document


_NO_RUN_PICKED = "Select a run to view details"
_WHAT_LOGS_OPENS = "Show what this run wrote to the log"


def _under_their_headings(stages: list[dict]) -> list[str | dict]:
    taken_out_last = len(STAGE_NUMBER) + 1
    rows: list[str | dict] = []
    heading = None
    for stage in sorted(stages, key=lambda stage: STAGE_NUMBER.get(stage.get("name", ""), taken_out_last)):
        stage_heading = STAGE_SECTION.get(stage.get("name", ""))
        if stage_heading is not None and stage_heading != heading:
            rows.append(stage_heading)
        heading = stage_heading
        rows.append(stage)
    return rows


class RunDetailWidget(QWidget):
    log_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD, MARGIN_STANDARD, MARGIN_STANDARD)

        self._record: RunRecord | None = None

        self._run_line = QLabel(_NO_RUN_PICKED)
        # Qt's AutoText guesses the format from the string and can draw a <span> or an <a> as
        # literal markup, so the label says RichText outright.
        self._run_line.setTextFormat(Qt.TextFormat.RichText)
        # QLabel emits linkActivated only while its interaction flags let the mouse reach links;
        # setting other flags (selectable text, say) replaces the default that does.
        self._run_line.linkActivated.connect(self._on_title_clicked)
        self._run_line.linkHovered.connect(self._say_what_is_under_the_pointer)
        layout.addWidget(self._run_line)

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
        mark, color = symbol_for(record.status)
        status = inline_icon(mark, color=color, size=self._run_line.fontMetrics().height()) if mark else ""
        self._run_line.setText(
            f"{format_run_start(record.started_at)}  |  Trigger: {record.trigger}"
            f"  |  Duration: {record.duration_seconds:.1f}s  |  Status: {status}"
            '  |  (<a href="log">logs</a>)'
        )
        self._run_line.setToolTip(record.status)

        self._table.clearSpans()
        self._table.clearContents()
        rows = _under_their_headings(record.stages)
        self._table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            if isinstance(row, str):
                self._show_heading(i, row)
            else:
                self._show_stage(i, row)

    def _show_heading(self, i: int, heading: str):
        font = self._table.font()
        font.setBold(True)
        band = QBrush(colors.BG_TERTIARY)
        for column in range(self._table.columnCount()):
            item = QTableWidgetItem(heading if column == 1 else "")
            item.setFont(font)
            item.setBackground(band)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._table.setItem(i, column, item)
        self._table.setSpan(i, 1, 1, self._table.columnCount() - 1)
        self._table.setRowHeight(i, self._table.verticalHeader().defaultSectionSize() + GAP_DIALOG)

    def _show_stage(self, i: int, stage: dict):
        stage_key = stage.get("name", "")
        self._table.setRowHeight(i, self._table.verticalHeader().defaultSectionSize())

        no_edit = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled

        num = STAGE_NUMBER.get(stage_key)
        num_item = QTableWidgetItem("\u2014" if num is None else str(num))
        num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        num_item.setForeground(GRAY)
        num_item.setFlags(no_edit)
        self._table.setItem(i, 0, num_item)

        name_item = QTableWidgetItem(stage_label(stage_key))
        name_item.setToolTip(as_rich_text(STAGE_TOOLTIPS.get(stage_key, "")))
        name_item.setFlags(no_edit)
        self._table.setItem(i, 1, name_item)

        status = stage.get("status", "")
        status_item = QTableWidgetItem()
        status_item.setIcon(status_icon(status))
        status_item.setToolTip(status)
        status_item.setFlags(no_edit)
        self._table.setItem(i, 2, status_item)

        duration = stage.get("duration_seconds", 0.0)
        dur_item = QTableWidgetItem(f"{duration:.1f}s")
        dur_item.setFlags(no_edit)
        self._table.setItem(i, 3, dur_item)

        details = details_of(stage.get("result"), stage.get("skip_reason"), stage_key)
        details_item = QTableWidgetItem(details)
        self._table.setItem(i, 4, details_item)

    def clear(self):
        self._record = None
        self._run_line.setText(_NO_RUN_PICKED)
        self._run_line.setToolTip("")
        self._table.setRowCount(0)

    def _say_what_is_under_the_pointer(self, href: str):
        if self._record is not None:
            self._run_line.setToolTip(_WHAT_LOGS_OPENS if href else self._record.status)

    def _on_title_clicked(self, _href: str):
        if self._record is not None:
            self.log_requested.emit(self._record)


class EvolverMainWindow(QMainWindow):
    log_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Evolver")
        self.setContentsMargins(0, MARGIN_STANDARD, 0, 0)
        self.setMinimumSize(800, 500)
        header = self._build_header()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, stretch=1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD, GAP_SMALL, MARGIN_STANDARD)

        self._history_list = QListWidget()
        self._history_list.setItemDelegate(_NoFocusRectDelegate(self._history_list))
        self._history_list.currentRowChanged.connect(self._on_history_selection)
        left_layout.addWidget(self._history_list)
        splitter.addWidget(left)

        self._detail_widget = RunDetailWidget()
        self._detail_widget.log_requested.connect(self.log_requested)
        splitter.addWidget(self._detail_widget)

        splitter.setSizes([300, 700])
        self.resize(max(1000, self._width_on_one_row_when_paused()), 600)

        self._records: list[RunRecord] = []
        self._runs_shown = config.RUNS_SHOWN

    def _build_header(self) -> QWidget:
        history_header = QLabel("Run history")
        font = history_header.font()
        font.setBold(True)
        history_header.setFont(font)
        self._next_run_label = QLabel("")
        self._header_labels = (history_header, self._next_run_label)

        self.run_now_action = RUN_NOW.action(self)
        self.pause_action = PAUSE.action(self)
        self.nonai_action = NONAI.action(self)
        self.nonai_switch = ToggleSwitch()
        self.nonai_action.triggered.connect(self.nonai_switch.click)
        self.settings_action = SETTINGS.action(self)
        self.stats_action = STATS.action(self)
        self.queue_action = QUEUE.action(self)
        self.review_trash_action = REVIEW_TRASH.action(self)
        self.restart_action = RESTART.action(self)
        self.quit_action = QUIT.action(self)
        self._button_groups = [
            [toolbar_button(self.run_now_action), toolbar_button(self.pause_action),
             SwitchButton(self.nonai_action, self.nonai_switch)],
            [toolbar_button(self.settings_action), toolbar_button(self.stats_action)],
            [toolbar_button(self.queue_action), toolbar_button(self.review_trash_action)],
            [toolbar_button(self.restart_action), toolbar_button(self.quit_action)],
        ]

        self._button_row = QWidget()
        self._button_row.setStyleSheet(toolbar_rules())
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self._button_row.setSizePolicy(policy)
        row = FlowLayout(self._button_row, spacing=BUTTON_GAP, row_spacing=BUTTON_ROW_GAP,
                         group_spacing=BUTTON_GROUP_GAP, least_row_height=self._tallest_button)
        row.setContentsMargins(MARGIN_STANDARD, 0, MARGIN_STANDARD, 0)
        for label in self._header_labels:
            row.addWidget(label)
        for group in self._button_groups:
            row.add_group(group, trailing=True)
        return self._button_row

    def _tallest_button(self) -> int:
        return max(button.sizeHint().height() for group in self._button_groups for button in group)

    def _width_on_one_row_when_paused(self) -> int:
        margins = self._button_row.layout().contentsMargins()
        items = [*self._header_labels, *(button for group in self._button_groups for button in group)]
        gaps = BUTTON_GAP * (len(items) - len(self._button_groups)) + BUTTON_GROUP_GAP * (len(self._button_groups) - 1)
        pause = _button_for(self._button_groups, self.pause_action)
        return (margins.left() + sum(item.sizeHint().width() for item in items) + gaps + margins.right()
                + _growth(pause, pause_or_resume(is_paused=True))
                + _growth(self._next_run_label, _in_parentheses(ScheduleStatus.longest_activity())))

    def commands(self):
        return {
            "run_now": self.run_now_action.triggered,
            "pause": self.pause_action.triggered,
            "nonai": self.nonai_switch.clicked,
            "settings": self.settings_action.triggered,
            "stats": self.stats_action.triggered,
            "queue": self.queue_action.triggered,
            "review_trash": self.review_trash_action.triggered,
            "restart": self.restart_action.triggered,
            "quit": self.quit_action.triggered,
        }

    def set_nonai_enabled(self, enabled: bool):
        self.nonai_switch.setChecked(enabled)

    def refresh_history(self):
        self._show_history(newest_runs(config.RUNS_DIR, self._runs_shown))

    def add_run(self, record: RunRecord) -> None:
        self._show_history([record, *self._records][:self._runs_shown])

    def _show_history(self, records: list[RunRecord]) -> None:
        self._records = records
        self._history_list.clear()
        for record in self._records:
            item = QListWidgetItem(
                status_icon(record.status),
                format_run_label(record.started_at, record.duration_seconds),
            )
            item.setToolTip(record.status)
            self._history_list.addItem(item)

        if self._records:
            self._history_list.setCurrentRow(0)

    def _on_history_selection(self, row: int):
        if 0 <= row < len(self._records):
            self._detail_widget.show_record(self._records[row])

    def show_schedule(self, status: ScheduleStatus):
        self.run_now_action.setEnabled(not status.is_running)
        set_label(self.pause_action, pause_or_resume(status.is_paused))
        self._next_run_label.setText(_in_parentheses(status.activity()))

    def closeEvent(self, event):
        event.ignore()
        self.hide()


def _button_for(groups: list[list[QToolButton]], action) -> QToolButton:
    [button] = [button for group in groups for button in group if button.defaultAction() is action]
    return button


def _in_parentheses(words: str) -> str:
    return f"({words})"


def _growth(button: QToolButton | QLabel, longer_text: str) -> int:
    metrics = button.fontMetrics()
    return max(0, metrics.horizontalAdvance(longer_text) - metrics.horizontalAdvance(button.text()))
