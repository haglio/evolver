"""Every place on disk the non-AI stage touches is redirected by its fixture.

A test that does not redirect one reads or writes the real machine's. That is
not hypothetical: ``NONAI_RETIRED_ROOT`` comes from the git-ignored overlay and
``NONAI_PRIORITY_MANIFEST`` is a path inside the checkout, so before both were
pinned here, four tests that retire an original moved their fixture videos into
the developer's real archive and then failed the assertion that the video had
gone to the bucket's ``2*`` folder. They were green on this Mac and on CI only
because neither has an overlay — which is the shape of hole a fixture cannot be
trusted to close by care.

So the two sets below are held as an equality against what the stage's modules
actually read, taken from the syntax tree: a new ambient read has to be filed
either as a place the fixture redirects or as one it deliberately leaves alone,
with the reason written down.
"""

import ast
import unittest
from pathlib import Path

from tests.temp_helpers import nonai_library_overrides, workspace_temp_dir
from tests.test_dead_code import PROJECT_ROOT

# The stage, its queue, the library shape they read it through, and the three
# helpers that resolve a library file's path or launch the encoder.
MODULES = (
    "tasks/nonai_upscale.py",
    "tasks/nonai_encode.py",
    "tasks/nonai_queue.py",
    "util/nonai_job.py",
    "util/nonai_library.py",
    "util/nonai_retire.py",
    "util/sidecar.py",
    "util/funscript.py",
    "util/topaz.py",
)

# Names that say where something is, so a case that does not redirect one is
# reading or writing the machine's own.
PLACES_ON_DISK = {
    "FUN_TIME_WATCH_STATS_FILE",
    "METADATA_DIR",
    "NONAI_ATTEMPTS_FILE",
    "NONAI_COOLDOWN_FILE",
    "NONAI_FFMPEG_LOG",
    "NONAI_JOB_STATE_FILE",
    "NONAI_PRIORITY_MANIFEST",
    "NONAI_RETIRED_ROOT",
    "NONAI_SKIP_MANIFEST",
    "NON_AI_DIR",
    "SCRIPT_LIBRARY_DIR",
    "VIDEO_LIBRARY_DIR",
}

# Everything else these modules read, and why a case may leave it as it is.
LEFT_AMBIENT = {
    "FFMPEG": "the Topaz install; named into a command line the tests mock away, "
              "and compared by file name against a pid's image -- never opened",
    "FUNSCRIPT_EXTENSION": "not a place",
    "LOW_DISK_WARNING_GB": "not a place",
    "NONAI_COMPLETE_DURATION_FRACTION": "not a place",
    "NONAI_COOLDOWN_MINUTES": "not a place",
    "NONAI_EXCLUDED_BUCKETS": "not a place",
    "NONAI_FALLBACK_DONE_DIR_NAME": "a folder name, resolved under NON_AI_DIR",
    "NONAI_MAX_ATTEMPTS": "not a place",
    "NONAI_MAX_RUNTIME_HOURS": "not a place",
    "NONAI_MIN_AVAILABLE_RAM_GB": "not a place",
    "NONAI_OUTPUT_SUFFIX": "not a place",
    "NONAI_PROCESSED_DIR_NAME": "a folder name, resolved under NON_AI_DIR",
    "NONAI_TARGET_LONG_EDGE": "not a place",
    "NONAI_TARGET_SHORT_EDGE": "not a place",
    "NONAI_UPSCALE_FILTER_TEMPLATE": "not a place",
    "NONAI_USER_IDLE_THRESHOLD_SECONDS": "not a place",
    "OUT_UPSCALED_DIR": "the AI outbox, reached only by sidecar.upscaled_video_path, "
                        "which no non-AI code path calls",
    "TVAI_MODEL_DIR": "the Topaz install; goes into the encoder's environment, "
                      "and no test launches one",
    "VIDEOAI_TAG_NONAI": "not a place",
    "VIDEO_EXTENSIONS": "not a place; one repo-wide answer to what counts as a video",
}


def _config_names_read() -> set[str]:
    found: set[str] = set()
    for name in MODULES:
        tree = ast.parse(Path(PROJECT_ROOT, name).read_text(encoding="utf-8"))
        found |= {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "config"
        }
    return found


class TestTheNonAiFixture(unittest.TestCase):
    def test_every_config_name_the_stage_reads_is_filed_one_way_or_the_other(self):
        self.assertEqual(
            _config_names_read(),
            PLACES_ON_DISK | set(LEFT_AMBIENT),
            "a new ambient read is either a place the fixture must redirect or "
            "one it may leave alone -- say which, and why, above",
        )

    def test_the_fixture_redirects_every_place_into_the_cases_own_tree(self):
        with workspace_temp_dir() as root:
            overrides = nonai_library_overrides(root)

            self.assertEqual(PLACES_ON_DISK - set(overrides), set())
            for name in sorted(PLACES_ON_DISK):
                with self.subTest(name=name):
                    value = overrides[name]
                    # None is the archive being unset, which is the public
                    # checkout's behaviour and keeps the original in-library.
                    if value is not None:
                        self.assertTrue(Path(value).is_relative_to(root))


if __name__ == "__main__":
    unittest.main()
