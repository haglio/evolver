from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import config
from tasks import upscale
from tests.temp_helpers import (
    LaneLibrary,
    override_config,
    touch_video,
    workspace_temp_dir,
    write_sidecar,
)
from util import lanes, origenerator_gallery, provenance, sidecar, topaz, video_kind
from util.media_files import partial_path


def library_dirs(root):
    return root / "sorted", root / "kino" / "2D" / "AI"


def kino_folders(out_dir):
    return {"KINO_DIR": out_dir.parent.parent}


def fake_run_ffmpeg(_in_file, tmp, _env, _settings=None, **kwargs):
    tmp.write_bytes(b"upscaled")
    return True


class TestUpscaleHelpers(unittest.TestCase):
    def test_an_upscale_is_made_once_it_is_in_either_orientations_folder_or_kinos_trash(self):
        with workspace_temp_dir() as root:
            _sorted, out = library_dirs(root)
            trash = root / "kino" / "trash"
            (out / "landscape" / "provider").mkdir(parents=True)
            (out / "portrait" / "provider").mkdir(parents=True)
            trash.mkdir(parents=True)

            with override_config(**kino_folders(out)):
                assert not upscale._already_made("provider", "a")

                p1 = out / "landscape" / "provider" / "a_topaz.mp4"
                p1.write_bytes(b"1")
                assert upscale._already_made("provider", "a")

                p1.unlink()
                p2 = out / "portrait" / "provider" / "a_topaz.mp4"
                p2.write_bytes(b"1")
                assert upscale._already_made("provider", "a")

                p2.unlink()
                p3 = trash / "a_topaz.mp4"
                p3.write_bytes(b"1")
                assert upscale._already_made("provider", "a")

    def test_a_genau_upscale_is_made_once_it_is_where_genau_plays_it_or_in_genaus_trash(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                spot = lanes.upscale_of("example-loop-clips", "landscape", "loop")
                assert not upscale._already_made("example-loop-clips", "loop")

                touch_video(spot)
                assert upscale._already_made("example-loop-clips", "loop")

                spot.unlink()
                touch_video(lib.genau_trash / "2D" / "AI" / spot.name)
                assert upscale._already_made("example-loop-clips", "loop")

    def test_run_processes_dynamic_source_and_creates_out_dir(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            source = "brandnew"
            in_file = sorted_dir / source / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                result = upscale.run(max_items=5)

            assert result.processed == 1
            assert result.failed == 0
            assert (out_dir / "landscape" / source).is_dir()
            assert (out_dir / "landscape" / source / "clip_topaz.mp4").exists()

    def test_run_upscales_the_sorted_tree_it_is_given_into_the_kino_folder(self):
        with workspace_temp_dir() as root:
            given_sorted, _ = library_dirs(root / "given")
            given_in = given_sorted / "examplesource" / "landscape" / "clip one.mp4"
            given_in.parent.mkdir(parents=True)
            given_in.write_bytes(b"video")

            ambient_sorted, ambient_out = library_dirs(root / "ambient")
            ambient_in = ambient_sorted / "examplesource" / "landscape" / "clip two.mp4"
            ambient_in.parent.mkdir(parents=True)
            ambient_in.write_bytes(b"video")

            with override_config(
                SORTED_DIR=ambient_sorted, **kino_folders(ambient_out),
                LOW_DISK_WARNING_GB=10 ** 9,
            ), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                result = upscale.run(
                    max_items=5,
                    folders=upscale.UpscaleFolders.configured(sorted=given_sorted),
                    low_disk=upscale.LowDiskWarning.configured(floor_gb=1),
                )

            assert result.processed == 1
            assert (ambient_out / "landscape" / "examplesource" / "clip one_topaz.mp4").exists()
            assert not (ambient_out / "landscape" / "examplesource" / "clip two_topaz.mp4").exists()
            assert ambient_in.exists()

    def test_a_kino_folder_outside_the_library_still_upscales(self):
        with workspace_temp_dir() as root, override_config(PROVIDER_SOURCE="provider"):
            sorted_dir, out_dir = library_dirs(root)
            in_file = sorted_dir / config.PROVIDER_SOURCE / "landscape" / "clip one.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            with override_config(**kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                 patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                result = upscale.run(
                    max_items=5,
                    folders=upscale.UpscaleFolders.configured(sorted=sorted_dir),
                    low_disk=upscale.LowDiskWarning.configured(floor_gb=1),
                )

            assert result.processed == 1
            assert result.failed == 0

    def test_collect_queued_videos_prioritizes_newly_sorted_files(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)

            priority = sorted_dir / "sourceB" / "portrait" / "priority.mp4"
            backlog = sorted_dir / "sourceA" / "landscape" / "backlog.mp4"
            priority.parent.mkdir(parents=True)
            backlog.parent.mkdir(parents=True)
            priority.write_bytes(b"video")
            backlog.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)):
                candidates = upscale.collect_queued_videos(upscale.UpscaleFolders.configured(), priority_files=[priority])

            assert candidates[0][0] == priority
            assert candidates[1][0] == backlog

    def test_run_removes_stale_partial_outputs_before_processing(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            source = "provider2"
            in_file = sorted_dir / source / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            stale_partial = partial_path(out_dir / "landscape" / source / "clip_topaz.mp4", "clip")
            stale_partial.parent.mkdir(parents=True)
            stale_partial.write_bytes(b"partial")

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                result = upscale.run(max_items=1)

            assert result.processed == 1
            assert not stale_partial.exists()
            assert (out_dir / "landscape" / source / "clip_topaz.mp4").exists()

    def test_the_file_an_encode_writes_until_promotion_carries_no_video_extension(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            in_file = sorted_dir / "examplesource" / "landscape" / "clip one.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            with override_config(**kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg) as run_ffmpeg, \
                 patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                upscale.run(
                    max_items=1,
                    folders=upscale.UpscaleFolders.configured(sorted=sorted_dir),
                    low_disk=upscale.LowDiskWarning.configured(floor_gb=1))

            written_to = run_ffmpeg.call_args.args[1]
            assert written_to.suffix.lower() not in config.VIDEO_EXTENSIONS

    def test_an_encode_ffmpeg_refused_is_recorded_as_a_failure(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            in_file = sorted_dir / "src" / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", return_value=False), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                result = upscale.run(max_items=5)

            assert result.processed == 0
            assert result.failed == 1

    def test_run_stops_early_when_budget_exceeded(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            for name in ("a", "b"):
                f = sorted_dir / "src" / "landscape" / f"{name}.mp4"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"video")

            with override_config(
                SORTED_DIR=sorted_dir, **kino_folders(out_dir),
                UPSCALE_RUN_BUDGET_SECONDS=1, UPSCALE_MIN_START_REMAINING_SECONDS=9999,
            ), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                result = upscale.run(max_items=10)

            assert result.processed == 1
            assert result.pending_after_run > 0

    def test_run_stops_early_on_low_disk(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            in_file = sorted_dir / "src" / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg") as ffmpeg_mock, \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=1), \
                     patch("tasks.upscale.show_error"):
                result = upscale.run(max_items=5)

            assert result.deferred_low_disk
            assert result.processed == 0
            ffmpeg_mock.assert_not_called()

    def test_run_records_failure_when_output_is_empty(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            in_file = sorted_dir / "src" / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            def fake_run_ffmpeg_empty(_in_file, tmp, _env, _settings=None, **kwargs):
                tmp.write_bytes(b"")
                return True

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg_empty), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                result = upscale.run(max_items=5)

            assert result.processed == 0
            assert result.failed == 1


FULL_DRIVE = 1
ROOMY_DRIVE = 10**15


class TestTheLowDiskWarning(unittest.TestCase):
    def runs(self, *free_bytes_each_run: int, clicked_dismiss: bool = False) -> MagicMock:
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            touch_video(sorted_dir / "src" / "landscape" / "clip.mp4")

            with override_config(**kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", return_value=False), \
                 patch("tasks.upscale.system_resources.free_bytes") as free_bytes, \
                 patch("tasks.upscale.show_error", return_value=clicked_dismiss) as show_error:
                for free in free_bytes_each_run:
                    free_bytes.return_value = free
                    upscale.run(
                        max_items=5,
                        folders=upscale.UpscaleFolders.configured(sorted=sorted_dir),
                        low_disk=upscale.LowDiskWarning.configured(
                            floor_gb=1, dismissed_file=root / "state" / "dismissed"))
        return show_error

    def test_the_low_disk_warning_offers_dismiss(self):
        show_error = self.runs(FULL_DRIVE)

        assert show_error.call_args.kwargs["dismissible"] is True

    def test_a_drive_with_30_gb_free_still_upscales_a_send(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            touch_video(sorted_dir / "src" / "landscape" / "clip.mp4")

            with override_config(**kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                 patch("tasks.upscale.system_resources.free_bytes", return_value=30 * 1024 ** 3), \
                 patch("tasks.upscale.show_error") as show_error:
                result = upscale.run(
                    max_items=5,
                    folders=upscale.UpscaleFolders.configured(sorted=sorted_dir),
                    low_disk=upscale.LowDiskWarning.configured(
                        dismissed_file=root / "state" / "dismissed"))

        assert result.processed == 1
        show_error.assert_not_called()

    def test_no_test_can_reach_the_dismissal_on_the_computer_running_the_suite(self):
        assert not config.LOW_DISK_WARNING_DISMISSED_FILE.is_relative_to(config.LOCAL_STATE_DIR)

    def test_ok_leaves_it_coming_back_every_run_the_drive_is_low(self):
        show_error = self.runs(FULL_DRIVE, FULL_DRIVE, FULL_DRIVE)

        assert show_error.call_count == 3

    def test_after_dismiss_it_stays_away_while_the_drive_stays_low(self):
        show_error = self.runs(FULL_DRIVE, FULL_DRIVE, FULL_DRIVE, clicked_dismiss=True)

        assert show_error.call_count == 1

    def test_once_a_run_finds_room_again_the_next_low_run_shows_it_once_more(self):
        show_error = self.runs(FULL_DRIVE, ROOMY_DRIVE, FULL_DRIVE, FULL_DRIVE, clicked_dismiss=True)

        assert show_error.call_count == 2

    def test_the_log_says_when_it_was_dismissed_and_when_room_brought_it_back(self):
        with self.assertLogs("tasks.upscale", level="INFO") as logged:
            self.runs(FULL_DRIVE, ROOMY_DRIVE, ROOMY_DRIVE, clicked_dismiss=True)

        said = [line for line in logged.output if "low-disk warning" in line]
        assert len(said) == 2
        assert "dismissed" in said[0]
        assert "room again" in said[1]


class TestWhatMadeTheUpscale(unittest.TestCase):
    def test_an_upscale_records_the_settings_and_the_version_of_them_that_made_it(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            touch_video(lib.sorted_dir / "examplesource" / "landscape" / "clip.mp4")
            upscaled = lib.kino_upscales / "landscape" / "examplesource" / "clip_topaz.mp4"

            with lib.config(), \
                 patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                 patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                upscale.run(max_items=1)

                stamp = sidecar.read(sidecar.sidecar_path(upscaled))[provenance.BLOCK][provenance.UPSCALE]

        assert (stamp["app"], stamp[provenance.METHOD], stamp[provenance.METHOD_VERSION]) == ("evolver", "ai_upscale", topaz.AI_UPSCALE.version)

    def test_a_text_to_video_clip_records_the_settings_it_was_given_instead(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(PROVIDER_SOURCE="exampleprovider"):
                touch_video(lib.sorted_dir / "exampleprovider" / "portrait" / "clip.mp4")
                upscaled = lib.kino_upscales / "portrait" / "exampleprovider" / "clip_topaz.mp4"
                write_sidecar(sidecar.sidecar_path(upscaled), {"video": {"prompt": "a prompt"}})

                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    upscale.run(max_items=1)

                stamp = sidecar.read(sidecar.sidecar_path(upscaled))[provenance.BLOCK][provenance.UPSCALE]

        assert (stamp[provenance.METHOD], stamp[provenance.METHOD_VERSION]) == ("ai_upscale_t2v", topaz.AI_UPSCALE_T2V.version)


class TestIsT2vProvider(unittest.TestCase):
    def test_true_for_provider_without_source_image(self):
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            json_path = meta_dir / "kino" / "2D" / "AI" / "landscape" / "provider" / "clip_topaz.json"
            json_path.parent.mkdir(parents=True)
            json_path.write_text(json.dumps({"video": {"prompt": "test"}}), encoding="utf-8")

            with override_config(METADATA_DIR=meta_dir):
                assert upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_false_for_provider_with_source_image(self):
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            json_path = meta_dir / "kino" / "2D" / "AI" / "landscape" / "provider" / "clip_topaz.json"
            json_path.parent.mkdir(parents=True)
            json_path.write_text(json.dumps({"video": {"prompt": "test"}, "source_image": {"positive_prompt": "img"}}), encoding="utf-8")

            with override_config(METADATA_DIR=meta_dir):
                assert not upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_false_for_another_source_beside_a_record_that_would_say_t2v(self):
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            json_path = meta_dir / "kino" / "2D" / "AI" / "landscape" / "provider2" / "clip_topaz.json"
            json_path.parent.mkdir(parents=True)
            json_path.write_text(json.dumps({"video": {"prompt": "test"}}), encoding="utf-8")

            with override_config(METADATA_DIR=meta_dir):
                assert not upscale._is_t2v_provider("provider2", "landscape", "clip")

    def test_the_provider_is_whoever_the_overlay_names(self):
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            json_path = meta_dir / "kino" / "2D" / "AI" / "landscape" / "examplesource" / "clip_topaz.json"
            json_path.parent.mkdir(parents=True)
            json_path.write_text(json.dumps({"video": {"prompt": "test"}}), encoding="utf-8")

            with override_config(METADATA_DIR=meta_dir, PROVIDER_SOURCE="examplesource"):
                assert upscale._is_t2v_provider("examplesource", "landscape", "clip")
                assert not upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_false_when_the_sidecar_is_not_readable_as_json(self):
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            json_path = (meta_dir / "kino" / "2D" / "AI" / "landscape" / "provider"
                         / "clip_topaz.json")
            json_path.parent.mkdir(parents=True)
            json_path.write_text('{"video": {"prompt"', encoding="utf-8")

            with override_config(METADATA_DIR=meta_dir):
                assert not upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_false_when_the_sidecar_holds_something_other_than_a_record(self):
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            json_path = (meta_dir / "kino" / "2D" / "AI" / "landscape" / "provider"
                         / "clip_topaz.json")
            json_path.parent.mkdir(parents=True)
            json_path.write_text("5", encoding="utf-8")

            with override_config(METADATA_DIR=meta_dir):
                assert not upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_false_when_the_sidecar_holds_only_the_video_kind(self):
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            json_path = meta_dir / "kino" / "2D" / "AI" / "landscape" / "provider" / "clip_topaz.json"
            json_path.parent.mkdir(parents=True)
            json_path.write_text(
                json.dumps({"video": {"type": video_kind.CLIP}}), encoding="utf-8",
            )

            with override_config(METADATA_DIR=meta_dir):
                assert not upscale._is_t2v_provider("provider", "landscape", "clip"), "a wrong answer bakes the text-to-video model into an encode nobody redoes"

    def test_false_when_metadata_missing(self):
        with workspace_temp_dir() as root:
            meta_dir = root / "meta"
            with override_config(METADATA_DIR=meta_dir):
                assert not upscale._is_t2v_provider("provider", "landscape", "clip")


class TestListeners(unittest.TestCase):
    def test_each_item_is_said_with_its_source_the_moment_it_is_filed_and_counted(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            for name in ("a", "b", "c"):
                f = sorted_dir / "src" / "landscape" / f"{name}.mp4"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"video")

            progress_calls, filed = [], []

            def on_filed(source):
                upscales = (out_dir / "landscape" / "src").iterdir()
                filed.append((source, sorted(upscale.name for upscale in upscales)))

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                upscale.run(max_items=10, listeners=upscale.Listeners(
                    on_progress=lambda cur, tot: progress_calls.append((cur, tot)),
                    on_filed=on_filed))

            assert filed == [("src", ["a_topaz.mp4"]), ("src", ["a_topaz.mp4", "b_topaz.mp4"]),
                             ("src", ["a_topaz.mp4", "b_topaz.mp4", "c_topaz.mp4"])]
            assert len(progress_calls) == 3
            assert progress_calls[0] == (1, 3)
            assert progress_calls[1] == (2, 3)
            assert progress_calls[2] == (3, 3)

    def test_a_failed_encode_is_counted_and_never_said_to_be_filed(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            for name in ("a", "b"):
                f = sorted_dir / "src" / "landscape" / f"{name}.mp4"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"video")

            progress_calls, filed = [], []

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", return_value=False), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                upscale.run(max_items=10, listeners=upscale.Listeners(
                    on_progress=lambda cur, tot: progress_calls.append((cur, tot)),
                    on_filed=filed.append))

            assert filed == []
            assert len(progress_calls) == 2
            assert progress_calls[-1] == (2, 2)

    def test_on_progress_not_required(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            f = sorted_dir / "src" / "landscape" / "clip.mp4"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                result = upscale.run(max_items=5)

            assert result.processed == 1


class TestSubprocessTimeout(unittest.TestCase):
    def test_an_encode_the_budget_stopped_is_not_counted_a_failure(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            in_file = sorted_dir / "src" / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=subprocess.TimeoutExpired("ffmpeg", 5)), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                result = upscale.run(max_items=5)

            assert result.stopped_at_budget == 1
            assert result.failed == 0
            assert result.processed == 0


    def test_run_breaks_loop_after_timeout(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            for name in ("a", "b"):
                f = sorted_dir / "src" / "landscape" / f"{name}.mp4"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"video")

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=subprocess.TimeoutExpired("ffmpeg", 5)) as mock_ffmpeg, \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                result = upscale.run(max_items=10)

            mock_ffmpeg.assert_called_once()
            assert result.stopped_at_budget == 1
            assert result.failed == 0
            assert result.pending_after_run == 2

    def test_the_video_the_budget_cut_off_is_still_pending(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            for name in ("a", "b"):
                f = sorted_dir / "src" / "landscape" / f"{name}.mp4"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(b"video")

            encodes = []

            def encode_then_run_out_of_time(in_file, tmp, *args, **kwargs):
                encodes.append(in_file)
                if len(encodes) == 1:
                    return fake_run_ffmpeg(in_file, tmp, *args, **kwargs)
                raise subprocess.TimeoutExpired("ffmpeg", 5)

            with (
                override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)),
                patch("tasks.upscale._run_ffmpeg", side_effect=encode_then_run_out_of_time),
                patch("tasks.upscale.system_resources.free_bytes", return_value=10**15),
            ):
                result = upscale.run(max_items=5)

            assert result.processed == 1
            assert result.stopped_at_budget == 1
            assert result.pending_after_run == 1

    def test_on_progress_reports_where_the_run_stopped(self):
        with workspace_temp_dir() as root:
            sorted_dir, out_dir = library_dirs(root)
            in_file = sorted_dir / "src" / "landscape" / "clip.mp4"
            in_file.parent.mkdir(parents=True)
            in_file.write_bytes(b"video")

            progress_calls = []

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=subprocess.TimeoutExpired("ffmpeg", 5)), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                upscale.run(max_items=5, listeners=upscale.Listeners(
                    on_progress=lambda cur, tot: progress_calls.append((cur, tot))))

            assert len(progress_calls) == 1
            assert progress_calls[0] == (0, 1)


class TestFfmpegWindowSuppression(unittest.TestCase):
    def test_run_ffmpeg_passes_create_no_window(self):
        with patch("tasks.upscale.subprocess.run") as mock_run:
            mock_run.return_value = unittest.mock.MagicMock(returncode=0)
            upscale._run_ffmpeg(
                Path("in.mp4"), Path("out.mp4"), {}, topaz.AI_UPSCALE,
            )
            kwargs = mock_run.call_args.kwargs
            assert "creationflags" in kwargs
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW


class TestSettingsSelection(unittest.TestCase):
    def _run_capturing_the_settings(self, root, sidecar_payload):
        video_lib = root / "videos"
        ai_dir = video_lib / "2D" / "AI"
        sorted_dir = ai_dir / "1_sorted"
        kino = video_lib / "kino"
        meta_dir = root / "meta"

        in_file = sorted_dir / "provider" / "landscape" / "clip.mp4"
        in_file.parent.mkdir(parents=True)
        in_file.write_bytes(b"video")

        json_path = (
            meta_dir / "kino" / "2D" / "AI"
            / "landscape" / "provider" / "clip_topaz.json"
        )
        json_path.parent.mkdir(parents=True)
        json_path.write_text(json.dumps(sidecar_payload), encoding="utf-8")

        encoded_with = []

        def fake_run_ffmpeg(_in_file, tmp, _env, settings, **kwargs):
            encoded_with.append(settings)
            tmp.write_bytes(b"upscaled")
            return True

        with override_config(VIDEO_LIBRARY_DIR=video_lib, AI_DIR=ai_dir, SORTED_DIR=sorted_dir,
                             KINO_DIR=kino, METADATA_DIR=meta_dir), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                 patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
            upscale.run(max_items=1)
        return encoded_with

    def test_run_uses_the_t2v_settings_for_t2v_provider(self):
        with workspace_temp_dir() as root:
            encoded_with = self._run_capturing_the_settings(root, {"video": {"prompt": "test"}})

            assert encoded_with == [topaz.AI_UPSCALE_T2V]

    def test_run_uses_the_default_settings_for_i2v_provider(self):
        with workspace_temp_dir() as root:
            encoded_with = self._run_capturing_the_settings(
                root, {"video": {"prompt": "test"}, "source_image": {"positive_prompt": "img"}}
            )

            assert encoded_with == [topaz.AI_UPSCALE]


class TestOrigeneratorsVideos(unittest.TestCase):
    def _upscale(self, root: Path, source: str):
        lib = LaneLibrary(root)
        video = touch_video(lib.sorted_dir / source / "portrait" / "scene one.mp4")
        origenerator = root / "origenerator"
        origenerator.mkdir()
        (origenerator / origenerator_gallery.PUBLISHED).write_text(
            json.dumps({"generated_fps": 16.0}), encoding="utf-8")
        encoded_with = []

        def encode(_in_file, tmp, _env, settings, **kwargs):
            encoded_with.append(settings)
            tmp.write_bytes(b"upscaled")
            return True

        with lib.config(), \
             patch("tasks.upscale._run_ffmpeg", side_effect=encode), \
             patch("tasks.upscale.ffprobe.frame_rate", return_value=Fraction(112)) as probed, \
             patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
            upscale.run(
                max_items=1,
                folders=upscale.UpscaleFolders.configured(origenerator=origenerator))
        return video, encoded_with, probed

    def test_take_the_settings_chosen_for_them_given_only_the_frames_their_model_made(self):
        with workspace_temp_dir() as root:
            video, encoded_with, probed = self._upscale(root, lanes.ORIGENERATOR_SOURCE)

        assert encoded_with == [topaz.framed(topaz.AI_UPSCALE_ORIGENERATOR, "portrait", video_fps=Fraction(112), generated_fps=Fraction(16))]
        probed.assert_called_once_with(video)

    def test_sent_down_the_genau_lane_take_the_same_settings(self):
        with workspace_temp_dir() as root:
            _, encoded_with, _ = self._upscale(root, "example-loop-clips")

        assert encoded_with == [topaz.framed(topaz.AI_UPSCALE_ORIGENERATOR, "portrait", video_fps=Fraction(112), generated_fps=Fraction(16))]

    def _upscaled_before(self, lib: LaneLibrary, source: str, stem: str, settings: topaz.Settings) -> Path:
        upscaled = touch_video(lanes.upscale_of(source, "portrait", stem))
        stamp = provenance.reconstructed("evolver", method=settings.name, method_version=settings.version)
        sidecar.update(sidecar.sidecar_path(upscaled),
                       lambda current: provenance.recorded(current, provenance.UPSCALE, stamp))
        return upscaled

    def test_upscaled_by_earlier_settings_are_upscaled_again_in_place(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                upscaled = self._upscaled_before(
                    lib, lanes.ORIGENERATOR_SOURCE, "scene one", topaz.AI_UPSCALE)
            _, encoded_with, _ = self._upscale(root, lanes.ORIGENERATOR_SOURCE)

            assert [settings.name for settings in encoded_with] == [topaz.AI_UPSCALE_ORIGENERATOR.name]
            assert upscaled.read_bytes() == b"upscaled"

    def test_never_upscaled_come_before_those_upscaled_again(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                self._upscaled_before(lib, lanes.ORIGENERATOR_SOURCE, "a scene", topaz.AI_UPSCALE)
                touch_video(lib.sorted_dir / lanes.ORIGENERATOR_SOURCE / "portrait" / "a scene.mp4")
                fresh = touch_video(lib.sorted_dir / lanes.ORIGENERATOR_SOURCE / "portrait" / "b scene.mp4")

                assert upscale.collect_queued_videos(upscale.UpscaleFolders.configured(), limit=1) == [(fresh, lanes.ORIGENERATOR_SOURCE, "portrait")]

    def test_one_a_player_holds_keeps_its_old_upscale_until_a_later_run(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                upscaled = self._upscaled_before(
                    lib, lanes.ORIGENERATOR_SOURCE, "scene one", topaz.AI_UPSCALE)
            with patch("tasks.upscale.retry_while_in_use", side_effect=PermissionError):
                self._upscale(root, lanes.ORIGENERATOR_SOURCE)

            assert upscaled.read_bytes() == b"video"
            assert sorted(p.name for p in upscaled.parent.iterdir()) == [upscaled.name]

    def test_upscaled_again_keep_their_place_by_date_a_second_after_the_old_one(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                upscaled = self._upscaled_before(
                    lib, lanes.ORIGENERATOR_SOURCE, "scene one", topaz.AI_UPSCALE)
            os.utime(upscaled, (1_700_000_000, 1_700_000_000))
            self._upscale(root, lanes.ORIGENERATOR_SOURCE)

            assert upscaled.read_bytes() == b"upscaled"
            assert upscaled.stat().st_mtime == 1700000001

    def test_upscaled_by_the_current_settings_are_left_alone(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                self._upscaled_before(
                    lib, lanes.ORIGENERATOR_SOURCE, "scene one", topaz.AI_UPSCALE_ORIGENERATOR)
            _, encoded_with, _ = self._upscale(root, lanes.ORIGENERATOR_SOURCE)

        assert encoded_with == []

    def test_from_any_other_source_keep_the_settings_they_had(self):
        with workspace_temp_dir() as root:
            _, encoded_with, _ = self._upscale(root, "example-provider-two")

        assert encoded_with == [topaz.AI_UPSCALE]


class TestUpscaleResultSurface(unittest.TestCase):
    def test_the_result_carries_only_counters_something_raises(self):
        assert {f.name for f in dataclasses.fields(upscale.UpscaleResult)} == {"processed", "failed", "stopped_at_budget", "deferred_low_disk", "pending_after_run"}


def test_a_folder_the_upscale_does_not_have_is_refused():
    with pytest.raises(TypeError, match="sorted_folder"):
        upscale.UpscaleFolders.configured(sorted_folder=Path("x"))


if __name__ == "__main__":
    unittest.main()
