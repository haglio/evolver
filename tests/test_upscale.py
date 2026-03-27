import unittest
from unittest.mock import patch

from tasks import upscale
from tests.temp_helpers import override_config, workspace_temp_dir


class TestUpscaleHelpers(unittest.TestCase):
    def test_already_processed_checks_all_locations(self):
        with workspace_temp_dir() as root:
            out = root / "out"
            weird = root / "weird"
            (out / "landscape" / "provider").mkdir(parents=True)
            (out / "portrait" / "provider").mkdir(parents=True)
            weird.mkdir(parents=True)

            with override_config(OUT_UPSCALED_DIR=out, WEIRD_DIR=weird):
                self.assertFalse(upscale._already_processed("provider", "a_topaz.mp4"))

                p1 = out / "landscape" / "provider" / "a_topaz.mp4"
                p1.write_bytes(b"1")
                self.assertTrue(upscale._already_processed("provider", "a_topaz.mp4"))

                p1.unlink()
                p2 = weird / "a_topaz.mp4"
                p2.write_bytes(b"1")
                self.assertTrue(upscale._already_processed("provider", "a_topaz.mp4"))

    def test_run_processes_dynamic_source_and_creates_out_dir(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            source = "brandnew"
            in_file = sorted_dir / source / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            def fake_run_ffmpeg(_in_file, tmp, _env):
                tmp.write_bytes(b"upscaled")
                return True

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=5)

            self.assertEqual(result.processed, 1)
            self.assertEqual(result.failed, 0)
            self.assertTrue((out_dir / "landscape" / source).is_dir())
            self.assertTrue((out_dir / "landscape" / source / "clip_topaz.mp4").exists())

    def test_collect_candidates_prioritizes_newly_sorted_files(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"

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
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            source = "provider2"
            in_file = sorted_dir / source / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            stale_partial = out_dir / "landscape" / source / "clip.partial.deadbeef.mp4"
            stale_partial.parent.mkdir(parents=True)
            stale_partial.write_bytes(b"partial")

            def fake_run_ffmpeg(_in_file, tmp, _env):
                tmp.write_bytes(b"upscaled")
                return True

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=1)

            self.assertEqual(result.processed, 1)
            self.assertFalse(stale_partial.exists())
            self.assertTrue((out_dir / "landscape" / source / "clip_topaz.mp4").exists())


    def test_run_records_failure_when_ffmpeg_returns_false(self):
        with workspace_temp_dir() as root:
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
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
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            for name in ("a", "b"):
                f = sorted_dir / "src" / "landscape" / f"{name}.mp4"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"video")

            def fake_run_ffmpeg(_in_file, tmp, _env):
                tmp.write_bytes(b"upscaled")
                return True

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
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
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
            sorted_dir = root / "sorted"
            out_dir = root / "out"
            weird_dir = root / "weird"
            in_file = sorted_dir / "src" / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            def fake_run_ffmpeg_empty(_in_file, tmp, _env):
                tmp.write_bytes(b"")
                return True

            with override_config(SORTED_DIR=sorted_dir, OUT_UPSCALED_DIR=out_dir, WEIRD_DIR=weird_dir):
                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg_empty), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    result = upscale.run(max_items=5)

            self.assertEqual(result.processed, 0)
            self.assertEqual(result.failed, 1)


if __name__ == "__main__":
    unittest.main()
