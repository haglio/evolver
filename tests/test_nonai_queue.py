"""Which non-AI clip is next, and why it beat the others.

These moved out of tests/test_nonai_upscale.py with the queue itself. They no
longer construct the stage to ask it: the three files a queue is built from are
arguments, so each test names the manifest or the stats file it wrote.
"""

import json
import unittest

from tasks import nonai_queue
from tests.temp_helpers import (
    make_video,
    override_config,
    workspace_temp_dir,
)
from tests.temp_helpers import (
    nonai_library_overrides as library_overrides,
)


def queue_files(root, overrides, *, pin_manifest=None):
    """The three files collect_candidates reads, defaulted to absent ones."""
    return {
        "skip_manifest": overrides["NONAI_SKIP_MANIFEST"],
        "pin_manifest": pin_manifest or root / "next.txt",
        "watch_stats_file": overrides["FUN_TIME_WATCH_STATS_FILE"],
    }


class TestCollectCandidates(unittest.TestCase):
    def test_finds_unprocessed_videos_in_triage_dirs_only(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            unsorted_video = make_video(non_ai / "larkin" / "0 unsorted" / "a.mp4")
            flagged_video = make_video(non_ai / "other" / "1 could use work" / "b.mp4")
            make_video(non_ai / "larkin" / "2 do not need work" / "retired.mp4")
            make_video(non_ai / "larkin" / "3_good_to_go" / "processed" / "done_iris2.mp4")
            make_video(non_ai / "actually_AI_but_funscripted" / "0 unsorted" / "ai.mp4")

            with override_config(**overrides):
                candidates = nonai_queue.collect_candidates(**queue_files(root, overrides))

            # Sort both sides: which bucket name sorts first is an accident of
            # the fixture's spelling, not something this test is about.
            self.assertEqual(
                sorted(c.path for c in candidates),
                sorted([flagged_video, unsorted_video]),
            )

    def test_ignores_videos_in_a_triage_dirs_manual_pre_work_substage(self):
        """A triage dir's first sub-stage holds manual pre-work (e.g. larkin's
        '1 could use work/1_originals_needing_trimming'); those clips are not
        ready for an unattended multi-hour encode."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            ready = make_video(non_ai / "larkin" / "1 could use work" / "ready.mp4")
            make_video(
                non_ai / "larkin" / "1 could use work"
                / "1_originals_needing_trimming" / "not yet.mp4"
            )

            with override_config(**overrides):
                candidates = nonai_queue.collect_candidates(**queue_files(root, overrides))

            self.assertEqual([c.path for c in candidates], [ready])

    def test_finds_videos_in_a_triage_dirs_upscale_ready_substages(self):
        """Past the manual-pre-work one, a triage dir's sub-stages say in their
        own names that the only thing left is the encode, so they queue too."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            work = non_ai / "larkin" / "1 could use work"

            good = make_video(
                work / "2_originals_good_trimwise_but_need_upscaling" / "good.mp4"
            )
            trimmed = make_video(
                work / "3_trimmed_from_originals_but_still_need_upscaling" / "trimmed.mp4"
            )
            make_video(work / "1_originals_needing_trimming" / "not yet.mp4")

            with override_config(**overrides):
                candidates = nonai_queue.collect_candidates(**queue_files(root, overrides))

            self.assertEqual(sorted(c.path for c in candidates), [good, trimmed])

    def test_pinned_videos_lead_the_queue_in_the_order_listed(self):
        """The pin manifest is how the user says "encode this one next", so it
        outranks the triage digit and every other ordering heuristic."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            pins = root / "next.txt"

            make_video(non_ai / "larkin" / "1 could use work" / "a.mp4")
            second = make_video(non_ai / "other" / "0 unsorted" / "y.mp4")
            first = make_video(non_ai / "larkin" / "0 unsorted" / "z.mp4")
            pins.write_text(
                "larkin/0 unsorted/z.mp4\nother/0 unsorted/y.mp4\n", encoding="utf-8"
            )

            with override_config(**overrides):
                candidates = nonai_queue.collect_candidates(
                    **queue_files(root, overrides, pin_manifest=pins))

            self.assertEqual([c.path for c in candidates][:2], [first, second])

    def test_a_pin_re_queues_a_video_that_already_has_a_processed_variant(self):
        """An existing variant normally reads as "already done". When it came
        from an older recipe, pinning is how the user asks for the redo."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]
            pins = root / "next.txt"

            original = make_video(non_ai / "larkin" / "1 could use work" / "scene.mp4")
            make_video(
                non_ai / "larkin" / "3_good_to_go" / "processed" / "scene_topaz.mp4"
            )
            pins.write_text("larkin/1 could use work/scene.mp4\n", encoding="utf-8")

            with override_config(**overrides):
                candidates = nonai_queue.collect_candidates(
                    **queue_files(root, overrides, pin_manifest=pins))

            self.assertEqual([c.path for c in candidates], [original])

    def test_excludes_originals_that_already_have_a_processed_variant(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            make_video(non_ai / "other" / "0 unsorted" / "kina.mp4")
            make_video(non_ai / "other" / "0 unsorted" / "kina_apo8_prob4.mp4")
            make_video(non_ai / "other" / "0 unsorted" / "lily.mp4")
            make_video(non_ai / "other" / "3 good to go" / "processed" / "lily_iris2.mp4")
            fresh = make_video(non_ai / "other" / "0 unsorted" / "fresh.mp4")

            with override_config(**overrides):
                candidates = nonai_queue.collect_candidates(**queue_files(root, overrides))

            self.assertEqual([c.path for c in candidates], [fresh])

    def test_excludes_skip_manifest_entries(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            make_video(non_ai / "other" / "0 unsorted" / "hopeless.mp4")
            fresh = make_video(non_ai / "other" / "0 unsorted" / "fresh.mp4")
            overrides["NONAI_SKIP_MANIFEST"].write_text(
                "other/0 unsorted/hopeless.mp4\tfailed twice\n", encoding="utf-8"
            )

            with override_config(**overrides):
                candidates = nonai_queue.collect_candidates(**queue_files(root, overrides))

            self.assertEqual([c.path for c in candidates], [fresh])

    def test_watched_videos_outrank_funscripted_ones(self):
        """Fun Time's watch stats (once its Nau tracking records them) are the
        strongest popularity signal; funscripts break ties among the unwatched."""
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            watched = make_video(non_ai / "larkin" / "0 unsorted" / "watched.mp4")
            scripted = make_video(non_ai / "larkin" / "0 unsorted" / "scripted.mp4")
            plain = make_video(non_ai / "larkin" / "0 unsorted" / "plain.mp4")
            disliked = make_video(non_ai / "larkin" / "0 unsorted" / "disliked.mp4")
            script = (overrides["SCRIPT_LIBRARY_DIR"] / "2D" / "non_AI" / "larkin"
                      / "0 unsorted" / "scripted.funscript")
            script.parent.mkdir(parents=True)
            script.write_text("{}", encoding="utf-8")
            overrides["FUN_TIME_WATCH_STATS_FILE"].write_text(json.dumps({
                str(watched).lower(): {"completions": 4, "skips": 0, "locks": 1},
                str(disliked).lower(): {"completions": 0, "skips": 3, "locks": 0},
            }), encoding="utf-8")

            with override_config(**overrides):
                candidates = nonai_queue.collect_candidates(**queue_files(root, overrides))

            self.assertEqual(
                [c.path for c in candidates], [watched, scripted, plain, disliked]
            )

    def test_orders_flagged_then_funscripted_then_the_rest(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            non_ai = overrides["NON_AI_DIR"]

            plain = make_video(non_ai / "larkin" / "0 unsorted" / "aaa plain.mp4")
            scripted = make_video(non_ai / "larkin" / "0 unsorted" / "zzz scripted.mp4")
            flagged = make_video(non_ai / "larkin" / "1 could use work" / "flagged.mp4")
            script = (overrides["SCRIPT_LIBRARY_DIR"] / "2D" / "non_AI" / "larkin"
                      / "0 unsorted" / "zzz scripted.funscript")
            script.parent.mkdir(parents=True)
            script.write_text("{}", encoding="utf-8")

            with override_config(**overrides):
                candidates = nonai_queue.collect_candidates(**queue_files(root, overrides))

            self.assertEqual([c.path for c in candidates], [flagged, scripted, plain])


class TestManifestEntries(unittest.TestCase):
    def test_a_missing_manifest_is_empty_rather_than_an_error(self):
        with workspace_temp_dir() as root:
            self.assertEqual(nonai_queue.manifest_entries(root / "none.txt"), [])

    def test_a_note_past_a_tab_is_the_users_own_and_not_part_of_the_path(self):
        with workspace_temp_dir() as root:
            path = root / "skip.txt"
            path.write_text(
                "larkin/0 unsorted/a.mp4\tfailed twice\n\nother/0 unsorted/b.mp4\n",
                encoding="utf-8",
            )

            self.assertEqual(
                nonai_queue.manifest_entries(path),
                ["larkin/0 unsorted/a.mp4", "other/0 unsorted/b.mp4"],
            )


class TestAddToSkipManifest(unittest.TestCase):
    def test_appends_the_relative_path_and_the_reason(self):
        with workspace_temp_dir() as root:
            overrides = library_overrides(root)
            video = make_video(overrides["NON_AI_DIR"] / "larkin" / "0 unsorted" / "a.mp4")
            manifest = root / "skip.txt"
            manifest.write_text("other/0 unsorted/b.mp4\tearlier\n", encoding="utf-8")

            with override_config(**overrides):
                nonai_queue.add_to_skip_manifest(manifest, video, "already tagged")

            self.assertEqual(
                manifest.read_text(encoding="utf-8").splitlines(),
                ["other/0 unsorted/b.mp4\tearlier",
                 "larkin/0 unsorted/a.mp4\talready tagged"],
            )


if __name__ == "__main__":
    unittest.main()
