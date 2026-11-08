from __future__ import annotations

import unittest
from pathlib import Path

from tests.product_sources import config_names_read
from tests.temp_helpers import nonai_library_overrides, workspace_temp_dir

MODULES = (
    "tasks/nonai_upscale.py",
    "tasks/nonai_files.py",
    "tasks/nonai_request.py",
    "tasks/nonai_encode.py",
    "tasks/nonai_progress.py",
    "tasks/nonai_queue.py",
    "util/nonai_job.py",
    "util/nonai_library.py",
    "util/nonai_retire.py",
    "util/sidecar.py",
    "util/script_library.py",
    "util/topaz.py",
)

PLACES_ON_DISK = {
    "FUN_TIME_WATCH_STATS_FILE",
    "GENERATED_SCRIPTS_DIR",
    "METADATA_DIR",
    "NONAI_ATTEMPTS_FILE",
    "NONAI_COOLDOWN_FILE",
    "NONAI_FFMPEG_LOG",
    "NONAI_JOB_STATE_FILE",
    "NONAI_PIN_LIST",
    "NONAI_REQUEST_FILE",
    "NONAI_RETIRED_ROOT",
    "VIDEO_SEARCH_ROOT",
    "NONAI_SKIP_LIST",
    "NON_AI_DIR",
    "SCRIPT_LIBRARY_DIR",
    "VIDEO_LIBRARY_DIR",
}

LEFT_AMBIENT = {
    "FFMPEG": "the Topaz install; named into a command line the tests mock away, "
              "and compared by file name against a pid's image -- never opened",
    "FUNSCRIPT_EXTENSION": "not a place",
    "NONAI_FALLBACK_DONE_DIR_NAME": "a folder name, resolved under NON_AI_DIR",
    "NONAI_OUTPUT_SUFFIX": "not a place",
    "NONAI_PROCESSED_DIR_NAME": "a folder name, resolved under NON_AI_DIR",
    "OUT_UPSCALED_DIR": "the AI outbox, reached only by sidecar.upscaled_video_path, "
                        "which no non-AI code path calls",
    "TVAI_MODEL_DIR": "the Topaz install; goes into the encoder's environment, "
                      "and no test launches one",
    "VIDEO_EXTENSIONS": "not a place: the suffixes a record's video may have",
}


class TestTheNonAiFixture(unittest.TestCase):
    def test_every_config_name_the_stage_reads_is_filed_one_way_or_the_other(self):
        assert config_names_read(*MODULES) == PLACES_ON_DISK | set(LEFT_AMBIENT), "a new ambient read is either a place the fixture must redirect or one it may leave alone -- say which, and why, above"

    def test_the_fixture_redirects_every_place_into_the_cases_own_tree(self):
        with workspace_temp_dir() as root:
            overrides = nonai_library_overrides(root)

            assert PLACES_ON_DISK - set(overrides) == set()
            for name in sorted(PLACES_ON_DISK):
                with self.subTest(name=name):
                    value = overrides[name]
                    if value is not None:
                        assert Path(value).is_relative_to(root)

    def test_an_archive_a_case_parks_beside_the_library_is_outside_its_search_root(self):
        with workspace_temp_dir() as root:
            overrides = nonai_library_overrides(root)

            assert not (root / "archive").is_relative_to(overrides["VIDEO_SEARCH_ROOT"])

    def test_a_cases_folder_is_outside_the_checkout_it_tests(self):
        with workspace_temp_dir() as root:
            assert not root.resolve().is_relative_to(PROJECT_ROOT)


if __name__ == "__main__":
    unittest.main()
