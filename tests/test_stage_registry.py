"""The GUI's stage registry must cover every stage the pipeline emits."""

import itertools
import re
import unittest
from pathlib import Path

import evolver
from gui.progress import ALL_STAGES
from gui.stats_window import STAGE_COLORS
from tests.color_support import band_fill, delta_e
from tests.test_dead_code import PROJECT_ROOT, _source_files
from tests.test_evolver import _patched_stages, _stage_mocks


class TestStageRegistry(unittest.TestCase):
    def test_the_registry_lists_exactly_the_stages_the_pipeline_emits(self):
        """The gate that can see a stage go missing, which nothing here could.

        `genau_deliver` ran for months with no registry row: it drew no
        progress bar, its duration was dropped from the chart, and the detail
        table fell back to numbering it with the number the stage after it
        already carried. Every test in this file read the registry and none of
        them imported `evolver`, so the two could not be compared.
        """
        mocks = _stage_mocks()
        with _patched_stages(mocks):
            result = evolver.run_pipeline()

        self.assertEqual([stage.name for stage in result.stages], ALL_STAGES)

    def test_gui_lists_the_genau_delivery_between_the_two_upscales(self):
        """Delivery runs straight after the AI upscale, so a clip made this run
        reaches Genau this run, and before the correspondence check, which
        would otherwise see the delivered clip's source still in 1_sorted with
        nothing beside it in the outbox."""
        self.assertIn("genau_deliver", ALL_STAGES)
        self.assertIn("upscale_non_ai", ALL_STAGES)
        self.assertEqual(ALL_STAGES.index("genau_deliver"), ALL_STAGES.index("upscale") + 1)
        self.assertEqual(ALL_STAGES.index("upscale_non_ai"), ALL_STAGES.index("genau_deliver") + 1)
        self.assertLess(ALL_STAGES.index("genau_deliver"), ALL_STAGES.index("verify"))

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

    def test_no_two_stage_bands_are_hard_to_tell_apart(self):
        """The chart stacks every stage as a band in one column, so a close
        pair is two bands nobody can separate and a legend that names the same
        colour twice.

        The floor is 20 Delta-E, argued from the units rather than fitted to
        this palette: ~2 is the smallest difference anyone sees and ~10 already
        reads as two colours, so 20 is a comfortable "obviously different"
        rather than the least that would pass. The palette this replaced scored
        8.8 and would fail it; the one here clears it by three.
        """
        worst, pair = min(
            (delta_e(band_fill(STAGE_COLORS[one]), band_fill(STAGE_COLORS[other])), (one, other))
            for one, other in itertools.combinations(ALL_STAGES, 2)
        )

        self.assertGreaterEqual(worst, 20.0, f"{pair[0]} and {pair[1]} differ by only {worst:.1f}")


if __name__ == "__main__":
    unittest.main()
