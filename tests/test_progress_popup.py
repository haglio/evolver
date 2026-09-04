import unittest
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QProgressBar


class TestPopupConstruction(unittest.TestCase):
    def setUp(self):
        from gui.progress_popup import ProgressPopup
        self.popup = ProgressPopup()

    def tearDown(self):
        self.popup.close()

    def test_has_a_bar_per_pipeline_stage(self):
        from tasks.stages import ALL_STAGES
        self.assertEqual(len(self.popup._bars), len(ALL_STAGES))

    def test_every_row_is_captioned_with_the_stage_label(self):
        """The bars are read while a run is in flight, so they say what the
        stage is rather than the key the run record files it under."""
        from PyQt6.QtWidgets import QLabel

        from tasks.stages import STAGE_LABELS

        captions = {label.text() for label in self.popup.findChildren(QLabel)}

        self.assertTrue(set(STAGE_LABELS.values()) <= captions)
        self.assertEqual(captions & set(STAGE_LABELS), set())

    def test_a_caption_is_never_clipped_by_the_column_it_sits_in(self):
        """The column is sized from the labels, not from a guess: the widest
        one is 137 px in this machine's default font and was 91 as a key, and
        the font is whatever the machine running it has."""
        from PyQt6.QtWidgets import QLabel

        from tasks.stages import STAGE_LABELS

        for label in self.popup.findChildren(QLabel):
            if label.text() in set(STAGE_LABELS.values()):
                with self.subTest(caption=label.text()):
                    self.assertGreaterEqual(
                        label.width(), label.fontMetrics().horizontalAdvance(label.text())
                    )

    def test_has_total_bar(self):
        self.assertIsInstance(self.popup._total_bar, QProgressBar)

    def test_all_bars_start_at_zero(self):
        for bar in self.popup._bars.values():
            self.assertEqual(bar.value(), 0)
        self.assertEqual(self.popup._total_bar.value(), 0)

    def test_total_bar_range_is_100_per_stage(self):
        from tasks.stages import ALL_STAGES
        self.assertEqual(self.popup._total_bar.maximum(), 100 * len(ALL_STAGES))

    def test_window_flags_include_tool_without_stay_on_top(self):
        flags = self.popup.windowFlags()
        self.assertFalse(flags & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(flags & Qt.WindowType.Tool)


class TestPopupStageLifecycle(unittest.TestCase):
    def setUp(self):
        from gui.progress_popup import ProgressPopup
        self.popup = ProgressPopup()

    def tearDown(self):
        self.popup.close()

    def test_stage_started_sets_indeterminate(self):
        self.popup.on_stage_started("sort")
        bar = self.popup._bars["sort"]
        # Indeterminate: max == 0
        self.assertEqual(bar.maximum(), 0)

    def test_stage_completed_sets_bar_to_100(self):
        self.popup.on_stage_started("sort")
        self.popup.on_stage_completed("sort")
        bar = self.popup._bars["sort"]
        self.assertEqual(bar.maximum(), 100)
        self.assertEqual(bar.value(), 100)

    def test_stage_skipped_sets_bar_to_100(self):
        self.popup.on_stage_completed("upscale")
        bar = self.popup._bars["upscale"]
        self.assertEqual(bar.value(), 100)

    def test_stage_error_sets_bar_to_100(self):
        self.popup.on_stage_completed("dupes")
        bar = self.popup._bars["dupes"]
        self.assertEqual(bar.value(), 100)


class TestPopupIntraProgress(unittest.TestCase):
    def setUp(self):
        from gui.progress_popup import ProgressPopup
        self.popup = ProgressPopup()

    def tearDown(self):
        self.popup.close()

    def test_stage_progress_updates_bar(self):
        self.popup.on_stage_started("upscale")
        self.popup.on_stage_progress("upscale", 3, 10)
        bar = self.popup._bars["upscale"]
        # Should switch from indeterminate to determinate
        self.assertEqual(bar.maximum(), 100)
        self.assertEqual(bar.value(), 30)

    def test_stage_progress_updates_total_bar(self):
        # Complete sort (contributes 100), then partial progress on upscale
        self.popup.on_stage_completed("sort")
        self.popup.on_stage_started("upscale")
        self.popup.on_stage_progress("upscale", 2, 5)
        # sort=100, upscale=40, rest=0 => total=140
        self.assertEqual(self.popup._total_bar.value(), 140)


class TestPopupTotalBar(unittest.TestCase):
    def setUp(self):
        from gui.progress_popup import ProgressPopup
        from tasks.stages import ALL_STAGES
        self.popup = ProgressPopup()
        self._all_stages = ALL_STAGES

    def tearDown(self):
        self.popup.close()

    def test_total_reaches_its_maximum_when_all_complete(self):
        for stage in self._all_stages:
            self.popup.on_stage_completed(stage)
        self.assertEqual(self.popup._total_bar.value(), 100 * len(self._all_stages))

    def test_skipped_stages_contribute_to_total(self):
        self.popup.on_stage_completed("sort")
        self.assertEqual(self.popup._total_bar.value(), 100)


class TestPopupAutoClose(unittest.TestCase):
    def setUp(self):
        from gui.progress_popup import ProgressPopup
        self.popup = ProgressPopup()

    def tearDown(self):
        self.popup.close()

    @patch("gui.progress_popup.QTimer")
    def test_pipeline_finished_schedules_close(self, mock_timer_class):
        self.popup.on_pipeline_finished()
        mock_timer_class.singleShot.assert_called_once()
        args = mock_timer_class.singleShot.call_args
        self.assertEqual(args[0][0], 2000)


class TestPopupPositioning(unittest.TestCase):
    def test_centers_on_anchor_window(self):
        from PyQt6.QtWidgets import QMainWindow

        from gui.progress_popup import ProgressPopup

        anchor = QMainWindow()
        anchor.resize(800, 600)
        anchor.move(200, 100)
        anchor.show()

        popup = ProgressPopup()
        popup.show_over(anchor)

        # Popup frame center should be near anchor frame center.
        # Y tolerance is larger because Tool windows have a smaller title
        # bar than QMainWindow on Windows (~18px difference).
        anchor_center = anchor.frameGeometry().center()
        popup_center = popup.frameGeometry().center()
        self.assertAlmostEqual(popup_center.x(), anchor_center.x(), delta=5)
        self.assertAlmostEqual(popup_center.y(), anchor_center.y(), delta=25)

        popup.close()
        anchor.close()


if __name__ == "__main__":
    unittest.main()
