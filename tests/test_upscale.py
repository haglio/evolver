import dataclasses
import json
import subprocess
import unittest
from unittest.mock import patch

import config
from tasks import upscale
from tests.temp_helpers import override_config, workspace_temp_dir


def library_dirs(root):
    """The three trees every upscale test builds: 1_sorted, the outbox, weird."""
    return root / "sorted", root / "out", root / "weird"


def fake_run_ffmpeg(_in_file, tmp, _env, _filter="", _tag="", **kwargs):
    """A successful encode: writes the temp output the stage promotes."""
    tmp.write_bytes(b"upscaled")
    return True



class TestUpscaleHelpers(unittest.TestCase):
    def test_already_processed_checks_all_locations(self):
        with workspace_temp_dir() as root:
            out = root / "out"
            weird = root / "weird"
            (out / "landscape" / "provider").mkdir(parents=True)
            (out / "portrait" / "provider").mkdir(parents=True)
            weird.mkdir(parents=True)

            with override_config(OUT_UPSCALED_DIR=out, WEIRD_DIR=weird):
                self.assertFalse(upscale._already_processed("provider", "a_topaz.mp4", out, weird))

                p1 = out / "landscape" / "provider" / "a_topaz.mp4"
                p1.write_bytes(b"1")
                self.assertTrue(upscale._already_processed("provider", "a_topaz.mp4", out, weird))

                p1.unlink()
                # The portrait arm on its own -- narrowing the loop to
                # ('landscape',) used to leave this test green (audit probe P3).
                p2 = out / "portrait" / "provider" / "a_topaz.mp4"
                p2.write_bytes(b"1")
                self.assertTrue(upscale._already_processed("provider", "a_topaz.mp4", out, weird))

                p2.unlink()
                p3 = weird / "a_topaz.mp4"
                p3.write_bytes(b"1")
                self.assertTrue(upscale._already_processed("provider", "a_topaz.mp4", out, weird))

    def test_run_processes_dynamic_source_and_creates_out_dir(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            source = "brandnew"
            in_file = sorted_dir / source / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=5)

            self.assertEqual(result.processed, 1)
            self.assertEqual(result.failed, 0)
            self.assertTrue((out_dir / "landscape" / source).is_dir())
            self.assertTrue((out_dir / "landscape" / source / "clip_topaz.mp4").exists())

    def test_run_upscales_between_the_three_trees_it_is_given(self):
        """The stage spans three trees and a disk floor, and says so now.

        `config` still answers when the caller names none of them, which is
        what the pipeline does and what every other test here relies on. The
        ambient three are pointed at a second sorted clip, so a stage still
        reading them would upscale that one instead.
        """
        with workspace_temp_dir() as root:
            given_sorted, given_out, given_weird = library_dirs(root / "given")
            given_in = given_sorted / "examplesource" / "landscape" / "clip one.mp4"
            given_in.parent.mkdir(parents=True)
            given_in.write_bytes(b"video")

            ambient_sorted, ambient_out, ambient_weird = library_dirs(root / "ambient")
            ambient_in = ambient_sorted / "examplesource" / "landscape" / "clip two.mp4"
            ambient_in.parent.mkdir(parents=True)
            ambient_in.write_bytes(b"video")

            with override_config(
                SORTED_DIR=ambient_sorted, OUT_UPSCALED_DIR=ambient_out, WEIRD_DIR=ambient_weird,
                LOW_DISK_WARNING_GB=10 ** 9,
            ):
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(
                        max_items=5,
                        sorted_dir=given_sorted,
                        outbox_dir=given_out,
                        weird_dir=given_weird,
                        low_disk_floor_gb=1,
                    )

            self.assertEqual(result.processed, 1)
            self.assertTrue((given_out / "landscape" / "examplesource" / "clip one_topaz.mp4").exists())
            self.assertFalse(ambient_out.exists())
            self.assertTrue(ambient_in.exists())

    def test_a_given_outbox_outside_the_library_still_upscales(self):
        """The scraped provider's own clips, upscaled into a folder of one's own.

        A given outbox is not under the library root, and the sidecar mirror
        is the library's — so asking for one there is a question with no
        answer rather than an error. The recipe choice degrades to the default
        exactly as it does for a clip that simply has no sidecar; it must not
        take the stage down before it has processed anything.
        """
        # The guard is reached only for a clip whose source name passes
        # `_is_t2v_provider`'s own hardcoded "provider" check (bug 7, held), so
        # the source is named here rather than taken from the overlay, which
        # agrees with that literal only by happening to.
        with workspace_temp_dir() as root, override_config(PROVIDER_SOURCE="provider"):
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            in_file = sorted_dir / config.PROVIDER_SOURCE / "landscape" / "clip one.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                 patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                result = upscale.run(
                    max_items=5,
                    sorted_dir=sorted_dir, outbox_dir=out_dir, weird_dir=weird_dir,
                    low_disk_floor_gb=1,
                )

            self.assertEqual(result.processed, 1)
            self.assertEqual(result.failed, 0)

    def test_collect_candidates_prioritizes_newly_sorted_files(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)

            priority = sorted_dir / "sourceB" / "portrait" / "priority.mp4"
            backlog = sorted_dir / "sourceA" / "landscape" / "backlog.mp4"
            priority.parent.mkdir(parents=True)
            backlog.parent.mkdir(parents=True)
            priority.write_bytes(b"video")
            backlog.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                candidates = upscale.collect_candidates(priority_files=[priority])

            self.assertEqual(candidates[0][0], priority)
            self.assertEqual(candidates[1][0], backlog)

    def test_run_removes_stale_partial_outputs_before_processing(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            source = "provider2"
            in_file = sorted_dir / source / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            stale_partial = out_dir / "landscape" / source / "clip.partial.deadbeef.mp4"
            stale_partial.parent.mkdir(parents=True)
            stale_partial.write_bytes(b"partial")

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=1)

            self.assertEqual(result.processed, 1)
            self.assertFalse(stale_partial.exists())
            self.assertTrue((out_dir / "landscape" / source / "clip_topaz.mp4").exists())


    def test_run_records_failure_when_ffmpeg_returns_false(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            in_file = sorted_dir / "src" / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", return_value=False), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=5)

            self.assertEqual(result.processed, 0)
            self.assertEqual(result.failed, 1)

    def test_run_stops_early_when_budget_exceeded(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            for name in ("a", "b"):
                f = sorted_dir / "src" / "landscape" / f"{name}.mp4"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"video")

            # Set a tiny budget so after the first item, remaining < min_start
            with override_config(
                SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir,
                UPSCALE_RUN_BUDGET_SECONDS=1, UPSCALE_MIN_START_REMAINING_SECONDS=9999,
            ):
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=10)

            # With budget=0, it should process the first item but stop before the second
            self.assertEqual(result.processed, 1)
            self.assertGreater(result.pending_after_run, 0)

    def test_run_stops_early_on_low_disk(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            in_file = sorted_dir / "src" / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg") as ffmpeg_mock, \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=1), \
                     patch("tasks.upscale.show_error_window"):
                    result = upscale.run(max_items=5)

            self.assertTrue(result.deferred_low_disk)
            self.assertEqual(result.processed, 0)
            ffmpeg_mock.assert_not_called()

    def test_run_records_failure_when_output_is_empty(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            in_file = sorted_dir / "src" / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            def fake_run_ffmpeg_empty(_in_file, tmp, _env, _filter="", _tag="", **kwargs):
                tmp.write_bytes(b"")
                return True

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg_empty), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=5)

            self.assertEqual(result.processed, 0)
            self.assertEqual(result.failed, 1)


class TestIsT2vProvider(unittest.TestCase):
    def test_true_for_provider_without_source_image(self):
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            json_path = meta_dir / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation" / "landscape" / "provider" / "clip_topaz.json"
            json_path.parent.mkdir(parents=True)
            json_path.write_text(json.dumps({"video": {"prompt": "test"}}), encoding="utf-8")

            with override_config(METADATA_DIR=meta_dir):
                self.assertTrue(upscale._is_t2v_provider("provider", "landscape", "clip", config.OUT_UPSCALED_DIR))

    def test_false_for_provider_with_source_image(self):
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            json_path = meta_dir / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation" / "landscape" / "provider" / "clip_topaz.json"
            json_path.parent.mkdir(parents=True)
            json_path.write_text(json.dumps({"video": {"prompt": "test"}, "source_image": {"positive_prompt": "img"}}), encoding="utf-8")

            with override_config(METADATA_DIR=meta_dir):
                self.assertFalse(upscale._is_t2v_provider("provider", "landscape", "clip", config.OUT_UPSCALED_DIR))

    def test_false_for_non_provider_source(self):
        # The sidecar is a valid t2v one, so only the source-name guard can
        # answer False here -- with no sidecar on disk the second check
        # answered False anyway and the guard could be deleted unseen (audit
        # probe P4b). Pins the current hardcoded "provider" comparison as it
        # behaves (bug 7, held for sign-off -- not fixed here).
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            json_path = meta_dir / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation" / "landscape" / "provider2" / "clip_topaz.json"
            json_path.parent.mkdir(parents=True)
            json_path.write_text(json.dumps({"video": {"prompt": "test"}}), encoding="utf-8")

            with override_config(METADATA_DIR=meta_dir):
                self.assertFalse(upscale._is_t2v_provider("provider2", "landscape", "clip", config.OUT_UPSCALED_DIR))

    def test_false_when_metadata_missing(self):
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            with override_config(METADATA_DIR=meta_dir):
                self.assertFalse(upscale._is_t2v_provider("provider", "landscape", "clip", config.OUT_UPSCALED_DIR))


class TestOnProgressCallback(unittest.TestCase):
    def test_on_progress_called_per_item(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            for name in ("a", "b", "c"):
                f = sorted_dir / "src" / "landscape" / f"{name}.mp4"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"video")

            progress_calls = []

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    upscale.run(max_items=10, on_progress=lambda cur, tot: progress_calls.append((cur, tot)))

            self.assertEqual(len(progress_calls), 3)
            self.assertEqual(progress_calls[0], (1, 3))
            self.assertEqual(progress_calls[1], (2, 3))
            self.assertEqual(progress_calls[2], (3, 3))

    def test_on_progress_counts_failures(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            for name in ("a", "b"):
                f = sorted_dir / "src" / "landscape" / f"{name}.mp4"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"video")

            progress_calls = []

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", return_value=False), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    upscale.run(max_items=10, on_progress=lambda cur, tot: progress_calls.append((cur, tot)))

            self.assertEqual(len(progress_calls), 2)
            self.assertEqual(progress_calls[-1], (2, 2))

    def test_on_progress_not_required(self):
        """Existing callers without on_progress still work."""
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            f = sorted_dir / "src" / "landscape" / "clip.mp4"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=5)

            self.assertEqual(result.processed, 1)


class TestSubprocessTimeout(unittest.TestCase):
    def test_run_records_timeout_when_ffmpeg_times_out(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            in_file = sorted_dir / "src" / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", side_effect=subprocess.TimeoutExpired("ffmpeg", 5)), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=5)

            self.assertEqual(result.timed_out, 1)
            self.assertEqual(result.failed, 1)
            self.assertEqual(result.processed, 0)


    def test_run_breaks_loop_after_timeout(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            for name in ("a", "b"):
                f = sorted_dir / "src" / "landscape" / f"{name}.mp4"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", side_effect=subprocess.TimeoutExpired("ffmpeg", 5)) as mock_ffmpeg, \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=10)

            mock_ffmpeg.assert_called_once()
            self.assertEqual(result.timed_out, 1)
            self.assertEqual(result.failed, 1)
            self.assertEqual(result.pending_after_run, 1)

    def test_on_progress_called_for_timed_out_item(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir, weird_dir = library_dirs(root)
            in_file = sorted_dir / "src" / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            progress_calls = []

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", side_effect=subprocess.TimeoutExpired("ffmpeg", 5)), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    upscale.run(max_items=5, on_progress=lambda cur, tot: progress_calls.append((cur, tot)))

            self.assertEqual(len(progress_calls), 1)
            self.assertEqual(progress_calls[0], (1, 1))


class TestFfmpegWindowSuppression(unittest.TestCase):
    def test_run_ffmpeg_passes_create_no_window(self):
        """ffmpeg must not spawn a visible console window on Windows."""
        from pathlib import Path
        with patch("tasks.upscale.subprocess.run") as mock_run:
            mock_run.return_value = unittest.mock.MagicMock(returncode=0)
            upscale._run_ffmpeg(
                Path("in.mp4"), Path("out.mp4"), {}, "filter", "tag",
            )
            kwargs = mock_run.call_args.kwargs
            self.assertIn("creationflags", kwargs)
            self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)


class TestFilterSelection(unittest.TestCase):
    def _run_capturing_ffmpeg_args(self, root, sidecar_payload):
        """Upscale one provider clip whose sidecar holds *sidecar_payload*, capturing the
        ffmpeg args.  The video tree nests under VIDEO_LIBRARY_DIR because a
        sidecar mirrors its clip's path relative to that root.
        """
        video_lib = root / "videos"
        ai_dir = video_lib / "2D" / "AI"
        sorted_dir = ai_dir / "1_sorted"
        out_dir = ai_dir / "2_outbox" / "upscaled_by_orientation"
        weird_dir = root / "weird"
        meta_dir = root / "meta"

        in_file = sorted_dir / "provider" / "landscape" / "clip.mp4"
        in_file.parent.mkdir(parents=True)
        in_file.write_bytes(b"video")

        json_path = (
            meta_dir / "2D" / "AI" / "2_outbox" / "upscaled_by_orientation"
            / "landscape" / "provider" / "clip_topaz.json"
        )
        json_path.parent.mkdir(parents=True)
        json_path.write_text(json.dumps(sidecar_payload), encoding="utf-8")

        captured_args = {}

        def fake_run_ffmpeg(_in_file, tmp, _env, filter_complex, videoai_tag, **kwargs):
            captured_args["filter_complex"] = filter_complex
            captured_args["videoai_tag"] = videoai_tag
            tmp.write_bytes(b"upscaled")
            return True

        with override_config(VIDEO_LIBRARY_DIR=video_lib, AI_DIR=ai_dir, SORTED_DIR=sorted_dir,
                             OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir, METADATA_DIR=meta_dir):
            with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                 patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                upscale.run(max_items=1)
        return captured_args

    def test_run_uses_t2v_filter_for_t2v_provider(self):
        with workspace_temp_dir() as root:
            captured_args = self._run_capturing_ffmpeg_args(root, {"video": {"prompt": "test"}})

            self.assertEqual(captured_args["filter_complex"], config.UPSCALE_FILTER_T2V_provider)
            self.assertEqual(captured_args["videoai_tag"], config.VIDEOAI_TAG_T2V_provider)

    def test_run_uses_default_filter_for_i2v_provider(self):
        with workspace_temp_dir() as root:
            captured_args = self._run_capturing_ffmpeg_args(
                root, {"video": {"prompt": "test"}, "source_image": {"positive_prompt": "img"}}
            )

            self.assertEqual(captured_args["filter_complex"], config.UPSCALE_FILTER_DEFAULT)
            self.assertEqual(captured_args["videoai_tag"], config.VIDEOAI_TAG_DEFAULT)


class TestUpscaleResultSurface(unittest.TestCase):
    def test_the_result_carries_only_counters_something_raises(self):
        """A counter nothing increments reads as a tally and is always a lie."""
        self.assertEqual(
            {f.name for f in dataclasses.fields(upscale.UpscaleResult)},
            {"processed", "failed", "timed_out", "deferred_low_disk", "pending_after_run"},
        )


if __name__ == "__main__":
    unittest.main()
