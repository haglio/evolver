from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import evolver
from check_correspondence import CorrespondenceResult
from check_duplicate_sizes import DuplicateSizesResult
from evolver import ALL_STAGES
from gui import stage_details
from gui.stage_details import NOTHING_TO_DO, SENTENCES, SKIP_REASONS, Sentence, details_of
from tasks.bookmarks_sync import BookmarksSyncResult
from tasks.clip_scripts import ClipScriptsResult
from tasks.genau_deliver import GenauDeliverResult
from tasks.nonai_group import NonAiGroupResult
from tasks.nonai_titles import NonAiTitleResult
from tasks.origenerator_commands import DowntimeResult
from tasks.prompt_scrape import PromptScrapeResult
from tasks.provenance_sweep import ProvenanceResult
from tasks.scene_scripts import SceneScriptsResult
from tasks.sort import SortResult
from tasks.stray_files import StrayFilesResult
from tasks.unsent_videos import UnsentVideosResult
from tasks.upscale import UpscaleResult
from tasks.video_kinds import VideoKindsResult
from tasks.watch_weights import WatchWeightsResult

RESULT_OF_STAGE = {
    "strays": StrayFilesResult, "withdrawn": UnsentVideosResult, "metadata": PromptScrapeResult,
    "sort": SortResult, "origenerator_downtime": DowntimeResult, "upscale": UpscaleResult,
    "genau_deliver": GenauDeliverResult, "verify": CorrespondenceResult,
    "watch_weights": WatchWeightsResult, "bookmarks": BookmarksSyncResult,
    "clip_scripts": ClipScriptsResult, "scene_scripts": SceneScriptsResult,
    "group_non_ai": NonAiGroupResult, "title_non_ai": NonAiTitleResult,
    "video_types": VideoKindsResult, "provenance": ProvenanceResult,
    "dupes": DuplicateSizesResult,
}
COUNTS_OF_A_STAGE_TAKEN_OUT = {"labels": {"copied": "int", "already": "int"}}


def _kinds_of_the_counts_of(stage: str) -> dict[str, str]:
    if stage in COUNTS_OF_A_STAGE_TAKEN_OUT:
        return COUNTS_OF_A_STAGE_TAKEN_OUT[stage]
    return {field.name: str(field.type).split("[")[0]
            for field in dataclasses.fields(RESULT_OF_STAGE[stage])}


def _fields_of(stage: str) -> set[str]:
    return set(_kinds_of_the_counts_of(stage))


THE_FILES_SORT_MOVED_ARE_FOR_THE_STAGES_AFTER_IT = {"sort": {"moved_files"}}


def _keys_read_by(stage: str, sentence: Sentence) -> set[str]:
    return ({part.key for part in sentence.parts}
            | THE_FILES_SORT_MOVED_ARE_FOR_THE_STAGES_AFTER_IT.get(stage, set()))


def _value_of(argument: ast.expr) -> str:
    if isinstance(argument, ast.Constant):
        return argument.value
    if isinstance(argument, ast.Name):
        return getattr(evolver, argument.id)
    assert isinstance(argument, ast.Attribute)
    assert isinstance(argument.value, ast.Name)
    return getattr(getattr(evolver, argument.value.id), argument.attr)


def _skip_reasons_evolver_gives() -> set[str]:
    tree = ast.parse(Path(evolver.__file__).read_text(encoding="utf-8"))
    return {
        _value_of(argument)
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "Skipped"
        for argument in call.args
    }


def test_every_stage_has_a_sentence_of_its_own():
    assert sorted(set(ALL_STAGES) - set(SENTENCES) - set(stage_details._SUMMARIZERS)) == []


def test_every_stage_with_a_sentence_names_the_counts_it_records():
    assert sorted(set(SENTENCES) ^ set(RESULT_OF_STAGE) ^ set(COUNTS_OF_A_STAGE_TAKEN_OUT)) == []


def test_every_reason_a_stage_is_skipped_has_a_sentence_of_its_own():
    assert sorted(_skip_reasons_evolver_gives() - set(SKIP_REASONS)) == []


def test_every_count_a_stage_records_reaches_its_sentence():
    unsaid = {stage: sorted(_fields_of(stage) ^ _keys_read_by(stage, sentence))
              for stage, sentence in SENTENCES.items()
              if _fields_of(stage) != _keys_read_by(stage, sentence)}

    assert unsaid == {}


def test_a_skipped_stage_says_why_in_words():
    assert details_of(None, "cpu_busy", "upscale") == "Waited: the computer's processor was too busy"


def test_an_older_skip_reason_with_no_sentence_is_shown_as_it_was_recorded():
    assert details_of(None, "made_up_reason", "upscale") == "made_up_reason"


def test_counts_read_as_a_sentence_and_a_zero_is_left_out():
    said = details_of({"moved": 3, "made_again": 0, "deleted_collisions": 1,
                       "skipped_unknown": 0, "moved_files": ["a.mp4"]}, None, "sort")

    assert said == "3 moved into 1_sorted, 1 already in 1_sorted and deleted from 0_inbox"


def test_one_of_a_thing_is_said_in_the_singular():
    assert details_of({"deleted": 1, "deleted_scripts": 2}, None, "withdrawn") == (
        "1 video deleted, 2 funscripts deleted")


def test_a_stage_that_found_no_work_says_so():
    assert details_of({"deleted": 0, "deleted_scripts": 0, "failed": 0}, None, "withdrawn") == (
        NOTHING_TO_DO)


def test_prompts_read_and_failures_are_shown_even_at_zero():
    said = details_of({"newly_scraped": 0, "errors": 58, "already_scraped": 0}, None, "metadata")

    assert said == "0 prompts read, 58 failed to read", (
        "a hidden zero makes a total failure read as a partial one")


def test_the_correspondence_check_names_what_does_not_match():
    said = details_of({"sorted_count": 412, "upscale_count": 411,
                       "orphan_sorted": ["Example Studio/portrait/video one.mp4"],
                       "orphan_upscales": [], "duplicates": {}, "missing_flicks": []},
                      None, "verify")

    assert said == ("412 1_sorted videos, 411 enhanced videos, 1 1_sorted video without its "
                    "enhanced video (Example Studio/portrait/video one.mp4)")


def test_a_flag_and_a_sentence_from_another_app_are_shown_as_words():
    said = details_of({"did": "started the experiments", "holds_the_graphics_card": True,
                       "failed": False}, None, "origenerator_downtime")

    assert said == "started the experiments, a LoRA is training on the graphics card"


def test_duplicate_sizes_count_their_groups():
    said = details_of({"scanned_count": 90, "duplicate_groups": {"100": ["a", "b"]}}, None, "dupes")

    assert said == "90 videos checked, 1 group of videos with the same size"


_A_VALUE_OF_EACH_KIND = {"int": 2, "float": 2.0, "bool": True, "str": "made-up",
                         "list": ["made-up name"], "dict": {"made-up name": ["one", "two"]}}


def _a_record_with_every_count_set(stage: str) -> dict:
    return {name: _A_VALUE_OF_EACH_KIND[kind] for name, kind in _kinds_of_the_counts_of(stage).items()}


def test_no_count_is_shown_as_the_codes_name_for_it():
    for stage in SENTENCES:
        record = _a_record_with_every_count_set(stage)
        said = details_of(record, None, stage)
        assert ("=" in said, [key for key in record if "_" in key and key in said]) == (
            False, []), stage


def test_a_stage_since_taken_out_still_reads_as_a_sentence_in_older_runs():
    assert details_of({"copied": 2, "already": 40}, None, "labels") == (
        "2 videos given their actions, 40 already had them")
