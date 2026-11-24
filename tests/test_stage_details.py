from __future__ import annotations

import ast
import dataclasses
import re
from pathlib import Path

import pytest

import evolver
from check_correspondence import CorrespondenceResult
from check_duplicate_sizes import DuplicateSizesResult
from evolver import ALL_STAGES, STAGE_TOOLTIPS
from gui import stage_details
from gui.stage_details import NOTHING_TO_DO, SENTENCES, SKIP_REASONS, Sentence, details_of
from tasks import funscript_drafts
from tasks.bookmarks_sync import BookmarksSyncResult
from tasks.clip_scripts import ClipScriptsResult
from tasks.funscript_drafts import FunscriptDraftsResult
from tasks.genau_deliver import GenauDeliverResult
from tasks.nonai_group import NonAiGroupResult
from tasks.nonai_titles import NonAiTitleResult
from tasks.origenerator_commands import DowntimeResult
from tasks.pcloud_stuck import PcloudStuckResult
from tasks.prompt_scrape import PromptScrapeResult
from tasks.provenance_sweep import ProvenanceResult
from tasks.scene_scripts import SceneScriptsResult
from tasks.sort import SortResult
from tasks.stray_files import StrayFilesResult
from tasks.unsent_videos import UnsentVideosResult
from tasks.upscale import UpscaleResult
from tasks.video_kinds import VideoKindsResult
from tasks.watch_weights import WatchWeightsResult

FLICK_WORDS = ("loopy", "loopies")
RESULT_OF_STAGE = {
    "strays": StrayFilesResult, "withdrawn": UnsentVideosResult, "metadata": PromptScrapeResult,
    "sort": SortResult, "origenerator_downtime": DowntimeResult, "upscale": UpscaleResult,
    "genau_deliver": GenauDeliverResult, "funscript_drafts": FunscriptDraftsResult,
    "verify": CorrespondenceResult,
    "watch_weights": WatchWeightsResult, "bookmarks": BookmarksSyncResult,
    "clip_scripts": ClipScriptsResult, "scene_scripts": SceneScriptsResult,
    "group_non_ai": NonAiGroupResult, "title_non_ai": NonAiTitleResult,
    "video_types": VideoKindsResult, "provenance": ProvenanceResult,
    "dupes": DuplicateSizesResult, "pcloud_stuck": PcloudStuckResult,
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


THE_REASONS_A_STAGE_HANDS_BACK = {"reason": {funscript_drafts.GOBLINSCRIPT_MISSING, funscript_drafts.STILL_DRAFTING,
                                              funscript_drafts.GOBLINSCRIPT_FAILED}}


def _skip_reasons_evolver_gives() -> set[str]:
    tree = ast.parse(Path(evolver.__file__).read_text(encoding="utf-8"))
    return {
        reason
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and getattr(call.func, "id", "") == "Skipped"
        for argument in call.args
        for reason in _reasons_in(argument)
    }


def _reasons_in(argument: ast.expr) -> set[str]:
    handed_back = THE_REASONS_A_STAGE_HANDS_BACK.get(getattr(argument, "id", ""))
    return handed_back if handed_back is not None else {_value_of(argument)}


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
    assert details_of(None, "cpu_busy", "upscale", FLICK_WORDS) == "waited because the computer's processor was too busy"


_NAMES_A_DETAIL_MAY_OPEN_WITH = {"Evolver", "Origenerator", "GoblinScript", "Topaz", "Chrome", "Fun"}


@pytest.mark.parametrize("said", [NOTHING_TO_DO, *SKIP_REASONS.values()])
def test_a_detail_starts_in_lowercase_unless_it_opens_with_a_name(said):
    assert said[0].islower() or said.split()[0] in _NAMES_A_DETAIL_MAY_OPEN_WITH


@pytest.mark.parametrize("said", [NOTHING_TO_DO, *SKIP_REASONS.values()])
def test_a_detail_never_opens_with_a_word_and_a_colon(said):
    assert ":" not in said.split()[0]


def test_an_older_skip_reason_with_no_sentence_is_shown_as_it_was_recorded():
    assert details_of(None, "made_up_reason", "upscale", FLICK_WORDS) == "made_up_reason"


def test_counts_read_as_a_sentence_and_a_zero_is_left_out():
    said = details_of({"moved": 3, "made_again": 0, "deleted_collisions": 1,
                       "skipped_unknown": 0, "moved_files": ["a.mp4"]}, None, "sort", FLICK_WORDS)

    assert said == "3 moved into `1_sorted`, 1 already in `1_sorted` and deleted from `0_inbox`"


def test_one_of_a_thing_is_said_in_the_singular():
    assert details_of({"deleted": 1, "deleted_scripts": 2}, None, "withdrawn", FLICK_WORDS) == (
        "1 video deleted, 2 funscripts deleted")


def test_genau_flicks_deleted_are_named_with_the_settings_word_apart_from_the_videos():
    said = details_of({"deleted": 2, "deleted_flicks": 1, "deleted_scripts": 0}, None, "withdrawn",
                      FLICK_WORDS)

    assert said == "2 videos deleted, 1 loopy deleted"


def test_a_stage_that_found_no_work_says_so():
    assert details_of({"deleted": 0, "deleted_flicks": 0, "deleted_scripts": 0, "failed": 0},
                      None, "withdrawn", FLICK_WORDS) == NOTHING_TO_DO


def test_a_stage_that_did_nothing_says_so_first_and_what_it_found_in_parentheses():
    said = details_of({"newly_scraped": 0, "handed_over": 0, "errors": 0, "already_scraped": 1064,
                       "skipped_failed": 0, "no_scrape_strat": 528}, None, "metadata", FLICK_WORDS)

    assert said == "nothing to do (1064 already read, 528 from a site Evolver hasn't been taught how to read prompts from yet)"


def test_a_scripts_sync_that_moved_nothing_says_so_first():
    assert details_of({"already_aligned": 4174}, None, "scripts", FLICK_WORDS) == "nothing to do (4174 already aligned)"


def test_a_stage_that_did_something_is_not_said_to_have_had_nothing_to_do():
    said = details_of({"written": 2, "already_scripted": 98}, None, "clip_scripts", FLICK_WORDS)

    assert said == "2 clips given a funscript, 98 clips already had one"


def test_a_stage_whose_work_failed_is_not_said_to_have_had_nothing_to_do():
    said = details_of({"deleted": 0, "deleted_scripts": 0, "failed": 3}, None, "withdrawn", FLICK_WORDS)

    assert said == "3 could not be deleted"


def test_every_part_of_a_sentence_says_whether_it_is_work_done_a_fault_or_a_finding():
    kinds = {part.kind for sentence in SENTENCES.values() for part in sentence.parts}

    assert kinds <= {stage_details.DONE, stage_details.WRONG, stage_details.FOUND}


def test_prompts_read_and_failures_are_shown_even_at_zero():
    said = details_of({"newly_scraped": 0, "errors": 58, "already_scraped": 0}, None, "metadata", FLICK_WORDS)

    assert said == "0 prompts read, 58 failed to read", (
        "a hidden zero makes a total failure read as a partial one")


def test_the_correspondence_check_names_what_does_not_match():
    said = details_of({"sorted_count": 412, "upscale_count": 411,
                       "orphan_sorted": ["Example Studio/portrait/video one.mp4"],
                       "orphan_upscales": [], "duplicates": {}, "missing_flicks": []},
                      None, "verify", FLICK_WORDS)

    assert said == ("412 `1_sorted` videos, 411 enhanced videos, 1 `1_sorted` video without its "
                    "enhanced video (Example Studio/portrait/video one.mp4)")


def test_the_correspondence_check_names_the_genau_lanes_copies_with_the_settings_word():
    said = details_of({"sorted_count": 412, "upscale_count": 411, "sorted_flicks": 1, "upscale_flicks": 30,
                       "orphan_sorted_flicks": ["example-loop-clips/portrait/loop one.mp4"],
                       "duplicate_flicks": {"loop two_topaz.mp4": ["a", "b"]}},
                      None, "verify", FLICK_WORDS)

    assert said == ("412 `1_sorted` videos, 1 `1_sorted` loopy, 411 enhanced videos, 30 enhanced loopies, "
                    "1 `1_sorted` loopy without its enhanced loopy (example-loop-clips/portrait/loop one.mp4), "
                    "1 enhanced loopy name in more than one place (loop two_topaz.mp4)")


def test_a_flag_and_a_sentence_from_another_app_are_shown_as_words():
    said = details_of({"did": "started the experiments", "holds_the_graphics_card": True,
                       "failed": False}, None, "origenerator_downtime", FLICK_WORDS)

    assert said == "started the experiments, a LoRA is training on the graphics card"


def test_duplicate_sizes_count_their_groups():
    said = details_of({"scanned_count": 90, "duplicate_groups": {"100": ["a", "b"]}}, None, "dupes", FLICK_WORDS)

    assert said == "90 videos checked, 1 group of videos with the same size"


_A_VALUE_OF_EACH_KIND = {"int": 2, "float": 2.0, "bool": True, "str": "made-up",
                         "list": ["made-up name"], "dict": {"made-up name": ["one", "two"]}}


def _a_record_with_every_count_set(stage: str) -> dict:
    return {name: _A_VALUE_OF_EACH_KIND[kind] for name, kind in _kinds_of_the_counts_of(stage).items()}


def test_no_count_is_shown_as_the_codes_name_for_it():
    for stage in SENTENCES:
        record = _a_record_with_every_count_set(stage)
        said = details_of(record, None, stage, FLICK_WORDS)
        assert ("=" in said, [key for key in record if "_" in key and key in said]) == (
            False, []), stage


def test_a_stage_since_taken_out_still_reads_as_a_sentence_in_older_runs():
    assert details_of({"copied": 2, "already": 40}, None, "labels", FLICK_WORDS) == (
        "2 videos given their actions, 40 already had them")


_FOLDER_NAMES = re.compile(r"\b(?:0_inbox|1_sorted|non_AI)\b")


def _words_on_screen() -> list[str]:
    words = [*STAGE_TOOLTIPS.values(), *SKIP_REASONS.values()]
    for sentence in SENTENCES.values():
        for part in sentence.parts:
            words += [value for name in ("many", "one", "words")
                      if isinstance(value := getattr(part, name, None), str)]
    return words


@pytest.mark.parametrize("words", _words_on_screen())
def test_a_folder_name_on_screen_is_written_in_backticks(words):
    assert not _FOLDER_NAMES.search(re.sub(r"`[^`]*`", "", words))
