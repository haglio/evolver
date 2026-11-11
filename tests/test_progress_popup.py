from __future__ import annotations

import unittest
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QLabel, QMainWindow, QProgressBar

from evolver import ALL_STAGES, STAGE_LABELS
from gui.progress_popup import BAR_WIDTH, ProgressPopup, _caption_width


class TestPopupConstruction(unittest.TestCase):
    def setUp(self):
        self.popup = ProgressPopup()

    def tearDown(self):
        self.popup.close()

    def test_has_a_bar_per_pipeline_stage(self):
        assert len(self.popup._bars) == len(ALL_STAGES)

    def test_every_row_is_captioned_with_the_stage_label(self):
        captions = {label.text() for label in self.popup.findChildren(QLabel)}

        assert set(STAGE_LABELS.values()) <= captions
        assert captions & set(STAGE_LABELS) == set()

    def test_a_caption_is_never_clipped_by_the_column_it_sits_in(self):
        for label in self.popup.findChildren(QLabel):
            if label.text() in set(STAGE_LABELS.values()):
                with self.subTest(caption=label.text()):
                    assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())

    def test_the_window_is_wide_enough_that_no_caption_runs_into_its_bar(self):
        self.popup.show()
        widest_caption = max(self.popup.fontMetrics().horizontalAdvance(label)
                             for label in STAGE_LABELS.values())
        for key, bar in self.popup._bars.items():
            with self.subTest(stage=key):
                assert bar.width() >= BAR_WIDTH
                assert bar.x() >= widest_caption

    def test_the_caption_column_widens_with_the_font(self):
        wider = QFont(self.popup.font())
        wider.setPointSizeF(wider.pointSizeF() * 2)
        widest = max(QFontMetrics(wider).horizontalAdvance(label) for label in STAGE_LABELS.values())

        assert _caption_width(wider) > widest

    def test_has_total_bar(self):
        assert isinstance(self.popup._total_bar, QProgressBar)

    def test_all_bars_start_at_zero(self):
        for bar in self.popup._bars.values():
            assert bar.value() == 0
        assert self.popup._total_bar.value() == 0

    def test_total_bar_range_is_100_per_stage(self):
        assert self.popup._total_bar.maximum() == 100 * len(ALL_STAGES)

    def test_window_flags_include_tool_without_stay_on_top(self):
        flags = self.popup.windowFlags()
        assert not flags & Qt.WindowType.WindowStaysOnTopHint
        assert flags & Qt.WindowType.Tool


class TestPopupStageLifecycle(unittest.TestCase):
    def setUp(self):
        self.popup = ProgressPopup()

    def tearDown(self):
        self.popup.close()

    def test_stage_started_sets_indeterminate(self):
        self.popup.on_stage_started("sort")
        bar = self.popup._bars["sort"]
        assert bar.maximum() == 0

    def test_stage_completed_sets_bar_to_100(self):
        self.popup.on_stage_started("sort")
        self.popup.on_stage_completed("sort")
        bar = self.popup._bars["sort"]
        assert bar.maximum() == 100
        assert bar.value() == 100

    def test_stage_skipped_sets_bar_to_100(self):
        self.popup.on_stage_completed("upscale")
        bar = self.popup._bars["upscale"]
        assert bar.value() == 100

    def test_stage_error_sets_bar_to_100(self):
        self.popup.on_stage_completed("dupes")
        bar = self.popup._bars["dupes"]
        assert bar.value() == 100


class TestPopupIntraProgress(unittest.TestCase):
    def setUp(self):
        self.popup = ProgressPopup()

    def tearDown(self):
        self.popup.close()

    def test_stage_progress_updates_bar(self):
        self.popup.on_stage_started("upscale")
        self.popup.on_stage_progress("upscale", 3, 10)
        bar = self.popup._bars["upscale"]
        assert bar.maximum() == 100
        assert bar.value() == 30

    def test_stage_progress_updates_total_bar(self):
        self.popup.on_stage_completed("sort")
        self.popup.on_stage_started("upscale")
        self.popup.on_stage_progress("upscale", 2, 5)
        assert self.popup._total_bar.value() == 140


class TestPopupTotalBar(unittest.TestCase):
    def setUp(self):
        self.popup = ProgressPopup()
        self._all_stages = ALL_STAGES

    def tearDown(self):
        self.popup.close()

    def test_total_reaches_its_maximum_when_all_complete(self):
        for stage in self._all_stages:
            self.popup.on_stage_completed(stage)
        assert self.popup._total_bar.value() == 100 * len(self._all_stages)

    def test_skipped_stages_contribute_to_total(self):
        self.popup.on_stage_completed("sort")
        assert self.popup._total_bar.value() == 100


class TestPopupAutoClose(unittest.TestCase):
    def setUp(self):
        self.popup = ProgressPopup()

    def tearDown(self):
        self.popup.close()

    @patch("gui.progress_popup.QTimer")
    def test_pipeline_finished_schedules_close(self, mock_timer_class):
        self.popup.on_pipeline_finished()
        mock_timer_class.singleShot.assert_called_once()
        args = mock_timer_class.singleShot.call_args
        assert args[0][0] == 2000


class TestPopupPositioning(unittest.TestCase):
    def test_centers_on_anchor_window(self):
        anchor = QMainWindow()
        anchor.resize(800, 600)
        anchor.move(200, 100)
        anchor.show()

        popup = ProgressPopup()
        popup.show_over(anchor)

        # Tool windows have a smaller title bar than QMainWindow on Windows.
        anchor_center = anchor.frameGeometry().center()
        popup_center = popup.frameGeometry().center()
        assert popup_center.x() == pytest.approx(anchor_center.x(), abs=5)
        assert popup_center.y() == pytest.approx(anchor_center.y(), abs=25)

        popup.close()
        anchor.close()


if __name__ == "__main__":
    unittest.main()
