"""The files the non-AI upscale stage touches, resolved once at its boundary."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tasks import nonai_files
from tests.temp_helpers import nonai_library_overrides, override_config, workspace_temp_dir


def test_each_path_is_the_one_given_or_else_the_configured_one():
    with workspace_temp_dir() as root:
        overrides = nonai_library_overrides(root)
        with override_config(**overrides):
            files = nonai_files.StageFiles.configured(job=Path("elsewhere/job.json"))

        assert files.job == Path("elsewhere/job.json")
        assert files.attempts == overrides["NONAI_ATTEMPTS_FILE"]
        assert files.cooldown == overrides["NONAI_COOLDOWN_FILE"]
        assert files.skip_list == overrides["NONAI_SKIP_LIST"]
        assert files.pin_list == overrides["NONAI_PIN_LIST"]
        assert files.watch_stats == overrides["FUN_TIME_WATCH_STATS_FILE"]
        assert files.request == overrides["NONAI_REQUEST_FILE"]


def test_the_candidates_are_collected_from_its_three_lists():
    files = nonai_files.StageFiles(
        job=Path("job"), attempts=Path("attempts"), cooldown=Path("cooldown"),
        skip_list=Path("skip"), pin_list=Path("pin"), watch_stats=Path("watch"),
        request=Path("request"))

    with patch("tasks.nonai_queue.collect_candidates", return_value=["a"]) as collect:
        assert files.candidates() == ["a"]

    collect.assert_called_once_with(skip_list=Path("skip"), pin_list=Path("pin"),
                                    watch_stats_file=Path("watch"))
