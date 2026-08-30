"""One declaration of the stages, and everything that must agree with it.

The pipeline's order, the popup's bars, the detail table's names, tooltips
and numbers and the chart's palette all come off ``tasks/stages.py``. What
is left to check is that the list really is the one the pipeline runs.
"""

import ast
import itertools
import re
import unittest
from pathlib import Path

from PyQt6.QtGui import QColor

import evolver
from gui import main_window
from gui.stats_window import STAGE_COLORS
from tasks.stages import ALL_STAGES, STAGE_LABELS, STAGES
from tests.color_support import band_fill, delta_e
from tests.test_dead_code import PROJECT_ROOT, _source_files
from tests.test_evolver import _patched_stages, _stage_mocks

# The stages with no `_STAGE_FAILED` rule, and why each one has none: nothing
# any of them does can come out wrong in a way the run should report.
# `sort` moves what it can identify and leaves the rest in the inbox;
# `clip_scripts` and `scene_scripts` write a funscript where one is missing and
# leave every existing one alone; `group_non_ai` is bookkeeping over whatever
# files happen to be there.
CANNOT_FAIL = frozenset({"sort", "clip_scripts", "scene_scripts", "group_non_ai"})


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

    def test_the_pipeline_spells_the_registry_s_order_and_nothing_else(self):
        """The same two lists, compared without running anything.

        `run_pipeline` names its stages one call at a time, because each
        carries its own arguments and skip branches — so the order is written
        twice and the second copy is checked rather than derived. This reads
        the names straight out of evolver.py's syntax tree, which means it
        also covers the four skip branches a single mocked run never takes,
        and it sees a registry row the pipeline runs nowhere as readily as a
        pipeline stage the registry does not name.

        A stage may be spelled several times running — `upscale` has three
        skip branches and one run — so consecutive repeats collapse. Two
        mentions that are not adjacent do not, because a stage reached from
        two places in the pipeline is exactly the drift worth failing on.
        """
        source = Path(PROJECT_ROOT, "evolver.py").read_text(encoding="utf-8")
        calls = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("_run_stage", "_skip_stage")
        ]
        calls.sort(key=lambda node: (node.lineno, node.col_offset))

        spelled = []
        for call in calls:
            first = call.args[0] if call.args else None
            self.assertTrue(
                isinstance(first, ast.Constant) and isinstance(first.value, str),
                f"the stage name at evolver.py:{call.lineno} is not a literal, "
                "so nothing can compare it to the registry",
            )
            spelled.append(first.value)

        self.assertEqual([name for name, _ in itertools.groupby(spelled)], ALL_STAGES)

    def test_a_stage_reaches_the_run_record_through_those_two_calls_and_no_other(self):
        """The gate above reads two call names, so it is only as good as the
        claim that a stage cannot be emitted any other way.

        `records.append(StageRecord(...))` inside one of the pipeline's skip
        branches would emit a stage that neither gate sees — the syntax-tree
        one because it is not a `_run_stage` call, the mocked run because it
        takes one path and never enters that branch.
        """
        tree = ast.parse(Path(PROJECT_ROOT, "evolver.py").read_text(encoding="utf-8"))
        emitters = set()
        enclosing = []

        def walk(node):
            named = isinstance(node, ast.FunctionDef)
            if named:
                enclosing.append(node.name)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "StageRecord"
            ):
                emitters.add(enclosing[-1] if enclosing else "<module>")
            for child in ast.iter_child_nodes(node):
                walk(child)
            if named:
                enclosing.pop()

        walk(tree)

        self.assertEqual(emitters, {"_run_stage", "_skip_stage"})

    def test_every_stage_either_has_a_verdict_rule_or_is_declared_unable_to_fail(self):
        """The last copy of the stage names, and the one that fails silently.

        A stage absent from `_STAGE_FAILED` cannot report an error — that is
        the table's design, so both a key misspelled there and a stage nobody
        wrote a rule for come out the same way: the stage keeps running, keeps
        finishing, and simply never fails. Nothing else in the run looks
        different either way.

        So the check is an equality rather than a subset, and the stages that
        genuinely cannot fail are named here. Adding a stage then has to
        answer "how does this one fail?" instead of defaulting to "it can't".
        """
        self.assertEqual(
            sorted(set(evolver._STAGE_FAILED) | CANNOT_FAIL),
            sorted(ALL_STAGES),
        )
        self.assertEqual(sorted(set(evolver._STAGE_FAILED) & CANNOT_FAIL), [])
        self.assertEqual(sorted(set(evolver._STAGE_HELD_BACK) - set(ALL_STAGES)), [])

    def test_every_stage_keyed_table_in_the_detail_view_names_a_real_stage(self):
        """Two more tables keyed by stage string, with the same silent shape.

        `_HEADLINE_FIELDS` exists so a "0 succeeded" stays on screen instead of
        vanishing and making a total failure look like a partial one, and the
        summarizers replace a bland numeric tally with the clip names and the
        words that say what went wrong. A stale key in either loses exactly
        that, with nothing raised and the row still drawn.

        The two summarizers were `stage_key == "upscale_non_ai"` and
        `== "scripts"` written into the dispatch, where no gate could see
        them; they are a table now so this can.
        """
        for table, name in (
            (main_window._HEADLINE_FIELDS, "_HEADLINE_FIELDS"),
            (main_window._SUMMARIZERS, "_SUMMARIZERS"),
        ):
            with self.subTest(table=name):
                self.assertEqual(sorted(set(table) - set(ALL_STAGES)), [])

    def test_the_registry_lists_the_genau_delivery_between_the_two_upscales(self):
        """Delivery runs straight after the AI upscale, so a clip made this run
        reaches Genau this run, and before the correspondence check, which
        would otherwise see the delivered clip's source still in 1_sorted with
        nothing beside it in the outbox."""
        self.assertIn("genau_deliver", ALL_STAGES)
        self.assertIn("upscale_non_ai", ALL_STAGES)
        self.assertEqual(ALL_STAGES.index("genau_deliver"), ALL_STAGES.index("upscale") + 1)
        self.assertEqual(ALL_STAGES.index("upscale_non_ai"), ALL_STAGES.index("genau_deliver") + 1)
        self.assertLess(ALL_STAGES.index("genau_deliver"), ALL_STAGES.index("verify"))

    def test_the_registry_lists_the_non_ai_grouping_stage_in_pipeline_order(self):
        self.assertIn("group_non_ai", ALL_STAGES)
        self.assertEqual(ALL_STAGES.index("group_non_ai"), ALL_STAGES.index("scripts") + 1)

    def test_the_registry_lists_the_script_writing_stages_before_the_sync_that_aligns_them(self):
        """Both stages carry a funscript between a clip and its scene, and the
        sync is what settles a new one across a video's version family — so
        neither can come after it."""
        self.assertIn("clip_scripts", ALL_STAGES)
        self.assertIn("scene_scripts", ALL_STAGES)
        self.assertEqual(ALL_STAGES.index("scene_scripts"), ALL_STAGES.index("clip_scripts") + 1)
        self.assertEqual(ALL_STAGES.index("scene_scripts"), ALL_STAGES.index("scripts") - 1)

    def test_the_readme_enumerates_the_stages_the_registry_declares(self):
        """The README walks a reader through the pipeline, which makes it a
        copy of the list like any other — and it had drifted furthest of all.
        It enumerated eleven stages, leaving out `clip_scripts`,
        `scene_scripts` and `group_non_ai` entirely, in an order matching
        neither the pipeline's nor anything else's: a reader saw Sort Inbox
        numbered 1 while the run detail table beside it printed 3.

        Each entry leads with the stage's shown name in bold, so the list can
        be read back and compared rather than maintained by hand.
        """
        readme = Path(PROJECT_ROOT, "README.md").read_text(encoding="utf-8")
        listed = re.findall(r"^\d+\. \*\*(.+?)\*\*", readme, re.MULTILINE)

        self.assertEqual(listed, [STAGE_LABELS[key] for key in ALL_STAGES])

    def test_nothing_writes_a_stage_number_of_its_own(self):
        """Ordering has one home, `STAGES`. A number typed into a log line, a
        docstring or a paragraph is a second copy that cannot be kept in step
        with it: four stages were still printing the position they held in a
        shorter pipeline, so `evolver.log` named a stage nothing else numbered
        that way, and the README carried a third numbering again.

        The prose is scanned as well as the code because that is where the
        worst of it was: twenty "Stage N" mentions across a module list and a
        page of notes, in two numbering schemes, neither the registry's.
        """
        scanned = _source_files(PROJECT_ROOT) + ["README.md", "docs/maintenance_notes.md"]
        offenders = sorted(
            f"{name}:{i}"
            for name in scanned
            for i, line in enumerate(Path(PROJECT_ROOT, name).read_text(encoding="utf-8").splitlines(), 1)
            if re.search(r"\bStage \d", line)
        )

        self.assertEqual(offenders, [])

    def test_every_declared_color_is_one_qt_can_paint(self):
        """The fourth column used to be a dict of `QColor`s, which rejected a
        bad channel where it was written. Plain integers do not, and the
        annotation is not checked at runtime: `QColor(300, 0, 0)` is simply
        invalid, and Qt paints an invalid color as black. That would give one
        stage a black band and a black legend swatch, and the Delta-E floor
        would not notice, because it measures the same invalid color on both
        sides of the comparison.
        """
        for stage in STAGES:
            with self.subTest(stage=stage.key):
                # Three channels, not four: a fourth would be an alpha Qt
                # accepts, and the band's alpha is the painter's to decide.
                self.assertEqual(len(stage.color), 3)
                self.assertTrue(QColor(*stage.color).isValid())

    def test_no_two_stage_bands_are_hard_to_tell_apart(self):
        """The chart stacks every stage as a band in one column, so a close
        pair is two bands nobody can separate and a legend that names the same
        color twice.

        The floor is 20 Delta-E, argued from the units rather than fitted to
        this palette: ~2 is the smallest difference anyone sees and ~10 already
        reads as two colors, so 20 is a comfortable "obviously different"
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
