from __future__ import annotations

import ast
import dataclasses
import itertools
import re
import unittest
from pathlib import Path

import pytest
from PyQt6.QtGui import QColor

from evolver import ALL_STAGES, STAGE_LABELS, STAGES
from gui import main_window
from gui.stats_window import STAGE_COLORS
from tasks.clip_scripts import ClipScriptsResult
from tasks.nonai_group import NonAiGroupResult
from tasks.nonai_titles import NonAiTitleResult
from tasks.nonai_upscale import NonAiUpscaleResult
from tasks.provenance_sweep import ProvenanceResult
from tasks.scene_scripts import SceneScriptsResult
from tasks.scripts_sync import ScriptsSyncResult
from tasks.sort import SortResult
from tasks.stray_files import StrayFilesResult
from tasks.video_actions import VideoActionsResult
from tasks.video_kinds import VideoKindsResult
from tests.color_support import CIE76_DELTA_E_OF_COLORS_OBVIOUSLY_DIFFERENT, band_fill, delta_e
from tests.product_sources import PROJECT_ROOT, product_sources
from util.stage_result import StageResult


def _keys_read_in_any_branch_of(function_names: tuple[str, ...]) -> set[str]:
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


WHY_IT_CANNOT_FAIL = {
    SortResult: "moves what it can identify and leaves the rest in the inbox",
    ClipScriptsResult: "writes a funscript where one is missing and leaves every existing one alone",
    SceneScriptsResult: "writes a funscript where one is missing and leaves every existing one alone",
    NonAiGroupResult: "bookkeeping over whatever files happen to be there",
    NonAiTitleResult: "bookkeeping over whatever files happen to be there",
    ProvenanceResult: "only fills in a record where none is; a gallery it cannot read leaves its "
                      "videos for a later run",
    StrayFilesResult: "what it cannot repair it reports, for a person to judge",
    VideoKindsResult: "a video it cannot measure is left for the next run",
    VideoActionsResult: "copies actions onto sidecars already there; a gallery it cannot read "
                       "leaves the actions for a later run",
}

_STAGES_THAT_MAKE_OR_MOVE_A_VIDEO = ("strays", "withdrawn", "sort", "upscale", "genau_deliver", "upscale_non_ai")


def _place(key: str) -> int:
    return ALL_STAGES.index(key)


class TestStageRegistry(unittest.TestCase):
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
                shown = _keys_read_in_any_branch_of(functions) | table_keys
                assert sorted(shown) == sorted(field.name for field in dataclasses.fields(result_type))

    def test_stray_files_run_first(self):
        assert ALL_STAGES[0] == "strays", (
            "every later stage finds videos by their extension and funscripts under the script "
            "tree, so a name strays repairs or a script it moves is invisible to them until it runs")

    def test_unsent_videos_are_deleted_before_the_scrape_and_the_sort(self):
        assert _place("withdrawn") < min(_place("metadata"), _place("sort")), (
            "a video on its way out must be given no sidecar and not be filed into 1_sorted")

    def test_genau_delivery_comes_straight_after_the_upscale(self):
        assert _place("genau_deliver") == _place("upscale") + 1, (
            "a video made this run reaches Genau this run")

    def test_genau_delivery_comes_before_the_correspondence_check(self):
        assert _place("genau_deliver") < _place("verify"), (
            "a flick made this run is finished before the check reads Genau's folder")

    def test_the_registry_lists_the_genau_delivery_between_the_two_upscales(self):
        assert _place("upscale_non_ai") == _place("genau_deliver") + 1

    def test_titles_come_after_the_grouping(self):
        assert _place("title_non_ai") > _place("group_non_ai"), (
            "the version families are what carry a clip's name to every version of its scene")

    def test_kinds_come_after_the_grouping(self):
        assert _place("video_types") > _place("group_non_ai"), (
            "the grouping makes a new non-AI video's sidecar, and the kind joins that one "
            "rather than making a second")

    def test_provenance_comes_after_every_stage_making_or_moving_a_video(self):
        assert _place("provenance") > max(map(_place, _STAGES_THAT_MAKE_OR_MOVE_A_VIDEO)), (
            "it only fills in what those stages left unrecorded")

    def test_provenance_comes_after_the_kinds(self):
        assert _place("provenance") > _place("video_types"), (
            "a video it records already has the sidecar the kinds stage made for it")

    def test_the_registry_lists_the_non_ai_grouping_stage_in_pipeline_order(self):
        assert "group_non_ai" in ALL_STAGES
        assert ALL_STAGES.index("group_non_ai") == ALL_STAGES.index("scripts") + 1

    def test_the_registry_lists_the_script_writing_stages_before_the_sync_that_aligns_them(self):
        assert "clip_scripts" in ALL_STAGES
        assert "scene_scripts" in ALL_STAGES
        assert ALL_STAGES.index("scene_scripts") == ALL_STAGES.index("clip_scripts") + 1
        assert ALL_STAGES.index("scene_scripts") == ALL_STAGES.index("scripts") - 1

    def test_the_phones_favorites_are_marked_before_bookmarks_reads_the_marks(self):
        assert ALL_STAGES.index("watch_weights") < ALL_STAGES.index("bookmarks")

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

    def test_every_declared_color_is_valid(self):
        # Qt paints an invalid QColor, such as QColor(300, 0, 0), as black.
        for stage in STAGES:
            with self.subTest(stage=stage.key):
                assert QColor(*stage.color).isValid(), (
                    "the band check would measure the same black on both sides and pass")

    def test_every_declared_color_leaves_the_bands_opacity_to_the_painter(self):
        for stage in STAGES:
            with self.subTest(stage=stage.key):
                assert len(stage.color) == len("rgb")

    def test_every_stage_result_that_can_never_fail_says_why(self):
        never_fail = {
            result_type for result_type in StageResult.__subclasses__()
            if not result_type.__module__.startswith("tests")
            and result_type.ok is StageResult.ok
        }

        assert never_fail == set(WHY_IT_CANNOT_FAIL)

    def test_no_two_stage_bands_are_hard_to_tell_apart(self):
        worst, pair = min(
            (delta_e(band_fill(STAGE_COLORS[one]), band_fill(STAGE_COLORS[other])), (one, other))
            for one, other in itertools.combinations(ALL_STAGES, 2)
        )

        assert worst >= CIE76_DELTA_E_OF_COLORS_OBVIOUSLY_DIFFERENT, f"{pair[0]} and {pair[1]} differ by only {worst:.1f}"


if __name__ == "__main__":
    unittest.main()
