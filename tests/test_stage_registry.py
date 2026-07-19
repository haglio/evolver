"""The GUI's stage registry must cover every stage the pipeline emits."""

import unittest

from gui.progress import ALL_STAGES
from gui.stats_window import STAGE_COLORS


class TestStageRegistry(unittest.TestCase):
    def test_gui_lists_the_non_ai_upscale_stage_after_the_ai_one(self):
        self.assertIn("upscale_non_ai", ALL_STAGES)
        self.assertEqual(ALL_STAGES.index("upscale_non_ai"), ALL_STAGES.index("upscale") + 1)

    def test_gui_lists_the_non_ai_grouping_stage_in_pipeline_order(self):
        self.assertIn("group_non_ai", ALL_STAGES)
        self.assertEqual(ALL_STAGES.index("group_non_ai"), ALL_STAGES.index("scripts") + 1)

    def test_gui_lists_clip_scripts_before_the_sync_that_aligns_what_it_writes(self):
        self.assertIn("clip_scripts", ALL_STAGES)
        self.assertEqual(ALL_STAGES.index("clip_scripts"), ALL_STAGES.index("scripts") - 1)

    def test_every_stage_has_a_chart_color(self):
        for stage in ALL_STAGES:
            with self.subTest(stage=stage):
                self.assertIn(stage, STAGE_COLORS)


if __name__ == "__main__":
    unittest.main()
