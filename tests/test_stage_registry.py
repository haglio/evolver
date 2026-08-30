"""The GUI's stage registry must cover every stage the pipeline emits."""

import re
import unittest
from pathlib import Path

from gui.progress import ALL_STAGES
from gui.stats_window import STAGE_COLORS
from tests.test_dead_code import PROJECT_ROOT, _source_files


class TestStageRegistry(unittest.TestCase):
    def test_gui_lists_the_non_ai_upscale_stage_after_the_ai_one(self):
        self.assertIn("upscale_non_ai", ALL_STAGES)
        self.assertEqual(ALL_STAGES.index("upscale_non_ai"), ALL_STAGES.index("upscale") + 1)

    def test_gui_lists_the_non_ai_grouping_stage_in_pipeline_order(self):
        self.assertIn("group_non_ai", ALL_STAGES)
        self.assertEqual(ALL_STAGES.index("group_non_ai"), ALL_STAGES.index("scripts") + 1)

    def test_gui_lists_the_script_writing_stages_before_the_sync_that_aligns_them(self):
        """Both stages carry a funscript between a clip and its scene, and the
        sync is what settles a new one across a video's version family — so
        neither can come after it."""
        self.assertIn("clip_scripts", ALL_STAGES)
        self.assertIn("scene_scripts", ALL_STAGES)
        self.assertEqual(ALL_STAGES.index("scene_scripts"), ALL_STAGES.index("clip_scripts") + 1)
        self.assertEqual(ALL_STAGES.index("scene_scripts"), ALL_STAGES.index("scripts") - 1)

    def test_no_module_writes_a_stage_number_of_its_own(self):
        """Ordering has one home, `STAGES`. A number typed into a log line or a
        docstring is a second copy that cannot be kept in step with it: four
        stages were still printing the position they held in a shorter
        pipeline, so `evolver.log` named a stage nothing else numbered that
        way.
        """
        offenders = sorted(
            f"{name}:{i}"
            for name in _source_files(PROJECT_ROOT)
            for i, line in enumerate(Path(PROJECT_ROOT, name).read_text(encoding="utf-8").splitlines(), 1)
            if re.search(r"\bStage \d", line)
        )

        self.assertEqual(offenders, [])

    def test_every_stage_has_a_chart_color(self):
        for stage in ALL_STAGES:
            with self.subTest(stage=stage):
                self.assertIn(stage, STAGE_COLORS)


if __name__ == "__main__":
    unittest.main()
