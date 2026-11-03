from __future__ import annotations

import ast
import dataclasses
import itertools
import re
import unittest
from pathlib import Path

import pytest
from PyQt6.QtGui import QColor

import evolver
from gui import main_window
from gui.stats_window import STAGE_COLORS
from tasks.nonai_upscale import NonAiUpscaleResult
from tasks.scripts_sync import ScriptsSyncResult
from tasks.stages import ALL_STAGES, STAGE_LABELS, STAGES
from tests.color_support import band_fill, delta_e
from tests.product_sources import PROJECT_ROOT, product_sources
from tests.test_evolver import _patched_stages, _stage_mocks

CANNOT_FAIL = frozenset({"strays", "sort", "clip_scripts", "scene_scripts", "group_non_ai",
                         "title_non_ai", "video_types", "provenance"})


def _result_keys_read(function_names: tuple[str, ...]) -> set[str]:
    tree = ast.parse(Path(PROJECT_ROOT, "gui", "main_window.py").read_text(encoding="utf-8"))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in function_names:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Subscript) and isinstance(inner.slice, ast.Constant):
                keys.add(inner.slice.value)
            elif (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "get" and inner.args
                    and isinstance(inner.args[0], ast.Constant)):
                keys.add(inner.args[0].value)
    return {key for key in keys if isinstance(key, str)}


class TestStageRegistry(unittest.TestCase):
    def test_the_registry_lists_exactly_the_stages_the_pipeline_emits(self):
        mocks = _stage_mocks()
        with _patched_stages(mocks):
            result = evolver.run_pipeline()

        assert [stage.name for stage in result.stages] == ALL_STAGES

    def test_the_pipeline_spells_the_registry_s_order_and_nothing_else(self):
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
            unnamed = (f"the stage name at evolver.py:{call.lineno} is not a literal, "
                       "so nothing can compare it to the registry")
            assert isinstance(first, ast.Constant), unnamed
            assert isinstance(first.value, str), unnamed
            spelled.append(first.value)

        assert [name for name, _ in itertools.groupby(spelled)] == ALL_STAGES

    def test_a_stage_reaches_the_run_record_through_those_two_calls_and_no_other(self):
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

        assert emitters == {"_run_stage", "_skip_stage"}

    def test_every_stage_either_has_a_verdict_rule_or_is_declared_unable_to_fail(self):
        assert sorted(set(evolver._STAGE_FAILED) | CANNOT_FAIL) == sorted(ALL_STAGES)
        assert sorted(set(evolver._STAGE_FAILED) & CANNOT_FAIL) == []
        assert sorted(set(evolver._STAGE_WARNED) - set(ALL_STAGES)) == []

    def test_every_stage_keyed_table_in_the_detail_view_names_a_real_stage(self):
        for table, name in (
            (main_window._HEADLINE_FIELDS, "_HEADLINE_FIELDS"),
            (main_window._SUMMARIZERS, "_SUMMARIZERS"),
        ):
            with self.subTest(table=name):
                assert sorted(set(table) - set(ALL_STAGES)) == []

    def test_every_counter_a_summarized_stage_declares_reaches_the_detail_view(self):
        scripts_keys = (
            {key for key, _label, _names in main_window._SCRIPTS_PROBLEMS}
            | {names for _key, _label, names in main_window._SCRIPTS_PROBLEMS if names}
            | {key for key, _label in main_window._SCRIPTS_ROUTINE}
        )
        for result_type, functions, table_keys in (
            (ScriptsSyncResult, ("_summarize_scripts_sync",), scripts_keys),
            (NonAiUpscaleResult,
             ("_summarize_nonai_upscale", "_whats_left", "_encode_state"),
             set()),
        ):
            with self.subTest(result=result_type.__name__):
                shown = _result_keys_read(functions) | table_keys
                assert sorted(shown) == sorted(field.name for field in dataclasses.fields(result_type))

    def test_the_registry_lists_the_genau_delivery_between_the_two_upscales(self):
        assert "genau_deliver" in ALL_STAGES
        assert "upscale_non_ai" in ALL_STAGES
        assert ALL_STAGES.index("genau_deliver") == ALL_STAGES.index("upscale") + 1
        assert ALL_STAGES.index("upscale_non_ai") == ALL_STAGES.index("genau_deliver") + 1
        assert ALL_STAGES.index("genau_deliver") < ALL_STAGES.index("verify")

    def test_the_stages_name_genaus_flicks_in_the_overlays_word(self):
        tips = {stage.key: stage.tooltip for stage in STAGES}

        assert "down the Genau lane, the delivered flick --" in tips["withdrawn"]
        assert tips["genau_deliver"].startswith("Move each upscaled Genau-lane flick out of 2_outbox into the folder Genau plays from")
        assert "redoes the flick forever" in tips["genau_deliver"]
        assert "a generation, a clip, a Genau flick --" in tips["video_types"]

    def test_the_registry_lists_the_non_ai_grouping_stage_in_pipeline_order(self):
        assert "group_non_ai" in ALL_STAGES
        assert ALL_STAGES.index("group_non_ai") == ALL_STAGES.index("scripts") + 1

    def test_the_registry_lists_the_script_writing_stages_before_the_sync_that_aligns_them(self):
        assert "clip_scripts" in ALL_STAGES
        assert "scene_scripts" in ALL_STAGES
        assert ALL_STAGES.index("scene_scripts") == ALL_STAGES.index("clip_scripts") + 1
        assert ALL_STAGES.index("scene_scripts") == ALL_STAGES.index("scripts") - 1

    def test_the_readme_enumerates_the_stages_the_registry_declares(self):
        readme = Path(PROJECT_ROOT, "README.md").read_text(encoding="utf-8")
        listed = re.findall(r"^\d+\. \*\*(.+?)\*\*", readme, re.MULTILINE)

        assert listed == [STAGE_LABELS[key] for key in ALL_STAGES]

    @pytest.mark.repo_check
    def test_nothing_writes_a_stage_number_of_its_own(self):
        scanned = [*product_sources(PROJECT_ROOT), "README.md", "docs/maintenance_notes.md"]
        offenders = sorted(
            f"{name}:{i}"
            for name in scanned
            for i, line in enumerate(Path(PROJECT_ROOT, name).read_text(encoding="utf-8").splitlines(), 1)
            if re.search(r"\bStage \d", line)
        )

        assert offenders == []

    def test_every_declared_color_is_one_qt_can_paint(self):
        for stage in STAGES:
            with self.subTest(stage=stage.key):
                assert len(stage.color) == 3
                assert QColor(*stage.color).isValid()

    def test_no_two_stage_bands_are_hard_to_tell_apart(self):
        worst, pair = min(
            (delta_e(band_fill(STAGE_COLORS[one]), band_fill(STAGE_COLORS[other])), (one, other))
            for one, other in itertools.combinations(ALL_STAGES, 2)
        )

        assert worst >= 20.0, f"{pair[0]} and {pair[1]} differ by only {worst:.1f}"


if __name__ == "__main__":
    unittest.main()
