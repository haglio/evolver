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
from tasks.origenerator_commands import Handed
from tests.gallery_fakes import FakeGallery, a_gallery_of, kept_at
from tests.temp_helpers import (
    LaneLibrary,
    override_config,
    touch_video,
    workspace_temp_dir,
)
from util import lanes, origenerator_gallery, provenance, topaz
from util.media_files import partial_path
from util.scraped_records import ScrapedRecords


def _upscaled(gallery=None, **given):
    return upscale.run(gallery=FakeGallery() if gallery is None else gallery, **given)


def _scraped(upscale_path: Path, record: dict) -> None:
    ScrapedRecords(config.SCRAPED_RECORDS_FILE).stage(upscale_path, record)


def library_dirs(root):
    return root / "sorted", root / "kino" / "2D" / "AI"


def kino_folders(out_dir):
    return {"KINO_DIR": out_dir.parent.parent,
            "ORIGENERATOR_DB_PATH": out_dir.parent.parent / "gallery.db"}


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
                result = _upscaled(max_items=5)

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
                result = _upscaled(
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
                result = _upscaled(
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
                result = _upscaled(max_items=1)

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
                _upscaled(
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
                result = _upscaled(max_items=5)

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
                result = _upscaled(max_items=10)

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
                result = _upscaled(max_items=5)

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
                result = _upscaled(max_items=5)

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
                    _upscaled(
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
                result = _upscaled(
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
    def test_an_upscale_hands_the_gallery_the_settings_and_the_version_of_them_that_made_it(self):
        gallery = FakeGallery()
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            touch_video(lib.sorted_dir / "examplesource" / "landscape" / "clip.mp4")
            upscaled = lib.kino_upscales / "landscape" / "examplesource" / "clip_topaz.mp4"

            with lib.config(), \
                 patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                 patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                _upscaled(gallery, max_items=1)

            ((recorded_for, stamp),) = gallery.upscales
            assert recorded_for == upscaled
            assert list(lib.metadata.rglob("*")) == []

        assert (stamp["app"], stamp[provenance.METHOD], stamp[provenance.METHOD_VERSION]) == ("evolver", "ai_upscale", topaz.AI_UPSCALE.version)

    def test_a_text_to_video_clip_hands_over_the_settings_it_was_given_instead(self):
        gallery = FakeGallery()
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(PROVIDER_SOURCE="exampleprovider"):
                touch_video(lib.sorted_dir / "exampleprovider" / "portrait" / "clip.mp4")
                _scraped(lib.kino_upscales / "portrait" / "exampleprovider" / "clip_topaz.mp4",
                         {"video": {"prompt": "a prompt"}})

                with patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                    _upscaled(gallery, max_items=1)

        ((_recorded_for, stamp),) = gallery.upscales
        assert (stamp[provenance.METHOD], stamp[provenance.METHOD_VERSION]) == ("ai_upscale_t2v", topaz.AI_UPSCALE_T2V.version)

    def test_the_gallery_is_told_the_upscale_is_filed_before_it_hears_what_made_it(self):
        heard = []

        class Hearing(FakeGallery):
            def upscaled(self, video, provenance):
                heard.append(("what made it", video.name))
                return super().upscaled(video, provenance)

        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            touch_video(lib.sorted_dir / "examplesource" / "landscape" / "clip.mp4")

            with lib.config(), \
                 patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                 patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                _upscaled(Hearing(), max_items=1, listeners=upscale.Listeners(
                    on_filed=lambda source, out: heard.append(("filed", out.name))))

        assert heard == [("filed", "clip_topaz.mp4"), ("what made it", "clip_topaz.mp4")]

    def test_a_gallery_that_does_not_take_what_made_an_upscale_is_said_in_the_log(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            touch_video(lib.sorted_dir / "examplesource" / "landscape" / "clip.mp4")

            with lib.config(), \
                 patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                 patch("tasks.upscale.system_resources.free_bytes", return_value=10**15), \
                 self.assertLogs("tasks.upscale", level="WARNING") as said:
                result = _upscaled(FakeGallery(Handed(done=0, no_row=1)), max_items=1)

        assert result.processed == 1
        assert any("did not record what made" in line for line in said.output)


class TestIsT2vProvider(unittest.TestCase):
    def _kino(self, root):
        origenerator = root / "origenerator"
        origenerator.mkdir()
        (origenerator / origenerator_gallery.PUBLISHED).write_text(json.dumps({
            origenerator_gallery.WORKFLOW_PREFIXES: {
                "text_to_video": "outside text-to-video:",
                "image_to_video": "outside image-to-video:"}}), encoding="utf-8")
        return override_config(KINO_DIR=root / "kino", ORIGENERATOR_DB_PATH=root / "gallery.db",
                               ORIGENERATOR_PROJECT_DIR=origenerator)

    def _in_the_gallery(self, root, source, workflow_name):
        upscaled = root / "kino" / "2D" / "AI" / "landscape" / source / "clip_topaz.mp4"
        a_gallery_of(root / "gallery.db",
                     [kept_at("outside-1", upscaled, workflow_name=workflow_name)])

    def _scraped_for(self, root, source, record):
        _scraped(root / "kino" / "2D" / "AI" / "landscape" / source / "clip_topaz.mp4", record)

    def test_true_for_provider_without_source_image(self):
        with workspace_temp_dir() as root, self._kino(root):
            self._scraped_for(root, "provider", {"video": {"prompt": "test"}})

            assert upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_false_for_provider_with_source_image(self):
        with workspace_temp_dir() as root, self._kino(root):
            self._scraped_for(root, "provider", {"video": {"prompt": "test"}, "source_image": {"positive_prompt": "img"}})

            assert not upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_false_for_another_source_beside_a_record_that_would_say_t2v(self):
        with workspace_temp_dir() as root, self._kino(root):
            self._scraped_for(root, "provider2", {"video": {"prompt": "test"}})

            assert not upscale._is_t2v_provider("provider2", "landscape", "clip")

    def test_the_provider_is_whoever_the_overlay_names(self):
        with workspace_temp_dir() as root, self._kino(root), \
                override_config(PROVIDER_SOURCE="examplesource"):
            self._scraped_for(root, "examplesource", {"video": {"prompt": "test"}})
            self._scraped_for(root, "provider", {"video": {"prompt": "test"}})

            assert upscale._is_t2v_provider("examplesource", "landscape", "clip")
            assert not upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_false_when_the_records_kept_for_the_gallery_cannot_be_read(self):
        with workspace_temp_dir() as root, self._kino(root):
            config.SCRAPED_RECORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
            config.SCRAPED_RECORDS_FILE.write_text('{"records": {"', encoding="utf-8")

            assert not upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_false_when_the_record_kept_is_empty(self):
        with workspace_temp_dir() as root, self._kino(root):
            self._scraped_for(root, "provider", {})

            assert not upscale._is_t2v_provider("provider", "landscape", "clip"), "a wrong answer bakes the text-to-video model into an encode nobody redoes"

    def test_false_when_nothing_was_scraped_and_the_gallery_has_no_row(self):
        with workspace_temp_dir() as root, self._kino(root):
            assert not upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_with_its_record_handed_over_the_gallery_row_says_it_was_made_from_words(self):
        with workspace_temp_dir() as root, self._kino(root):
            self._in_the_gallery(root, "provider", "outside text-to-video:provider")

            assert upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_with_its_record_handed_over_the_gallery_row_says_it_was_made_from_an_image(self):
        with workspace_temp_dir() as root, self._kino(root):
            self._in_the_gallery(root, "provider", "outside image-to-video:provider")

            assert not upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_a_row_that_says_neither_reads_as_made_from_an_image(self):
        with workspace_temp_dir() as root, self._kino(root):
            self._in_the_gallery(root, "provider", "outside:provider")

            assert not upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_the_record_kept_for_the_gallery_outranks_what_the_gallery_says(self):
        with workspace_temp_dir() as root, self._kino(root):
            self._in_the_gallery(root, "provider", "outside text-to-video:provider")
            self._scraped_for(root, "provider", {"video": {"prompt": "test"}, "source_image": {"positive_prompt": "img"}})

            assert not upscale._is_t2v_provider("provider", "landscape", "clip")

    def test_a_gallery_that_cannot_be_read_reads_as_made_from_an_image(self):
        with workspace_temp_dir() as root, self._kino(root):
            (root / "gallery.db").write_bytes(b"not a database, made up for this test")

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

            def on_filed(source, out):
                upscales = (out_dir / "landscape" / "src").iterdir()
                filed.append((source, out.name, sorted(upscale.name for upscale in upscales)))

            with override_config(SORTED_DIR=sorted_dir, **kino_folders(out_dir)), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                     patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
                _upscaled(max_items=10, listeners=upscale.Listeners(
                    on_progress=lambda cur, tot: progress_calls.append((cur, tot)),
                    on_filed=on_filed))

            assert filed == [("src", "a_topaz.mp4", ["a_topaz.mp4"]),
                             ("src", "b_topaz.mp4", ["a_topaz.mp4", "b_topaz.mp4"]),
                             ("src", "c_topaz.mp4", ["a_topaz.mp4", "b_topaz.mp4", "c_topaz.mp4"])]
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
                _upscaled(max_items=10, listeners=upscale.Listeners(
                    on_progress=lambda cur, tot: progress_calls.append((cur, tot)),
                    on_filed=lambda source, out: filed.append(out)))

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
                result = _upscaled(max_items=5)

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
                result = _upscaled(max_items=5)

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
                result = _upscaled(max_items=10)

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
                result = _upscaled(max_items=5)

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
                _upscaled(max_items=5, listeners=upscale.Listeners(
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
    def _run_capturing_the_settings(self, root, scraped):
        video_lib = root / "videos"
        ai_dir = video_lib / "2D" / "AI"
        sorted_dir = ai_dir / "1_sorted"
        kino = video_lib / "kino"
        meta_dir = root / "meta"

        in_file = sorted_dir / "provider" / "landscape" / "clip.mp4"
        in_file.parent.mkdir(parents=True)
        in_file.write_bytes(b"video")
        _scraped(kino / "2D" / "AI" / "landscape" / "provider" / "clip_topaz.mp4", scraped)

        encoded_with = []

        def fake_run_ffmpeg(_in_file, tmp, _env, settings, **kwargs):
            encoded_with.append(settings)
            tmp.write_bytes(b"upscaled")
            return True

        with override_config(VIDEO_LIBRARY_DIR=video_lib, AI_DIR=ai_dir, SORTED_DIR=sorted_dir,
                             KINO_DIR=kino, METADATA_DIR=meta_dir), patch("tasks.upscale._run_ffmpeg", side_effect=fake_run_ffmpeg), \
                 patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
            _upscaled(max_items=1)
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

        with lib.config(ORIGENERATOR_DB_PATH=root / "gallery.db"), \
             patch("tasks.upscale._run_ffmpeg", side_effect=encode), \
             patch("tasks.upscale.ffprobe.frame_rate", return_value=Fraction(112)) as probed, \
             patch("tasks.upscale.system_resources.free_bytes", return_value=10**15):
            _upscaled(
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
        a_gallery_of(lib.search_root.parent / "gallery.db",
                     [kept_at("made-0", upscaled, upscale_provenance=json.dumps(stamp))])
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
            with lib.config(ORIGENERATOR_DB_PATH=root / "gallery.db"):
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

    def test_one_the_gallery_has_no_row_for_is_left_alone(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                upscaled = touch_video(lanes.upscale_of(lanes.ORIGENERATOR_SOURCE, "portrait", "scene one"))
                a_gallery_of(root / "gallery.db", [])
            _, encoded_with, _ = self._upscale(root, lanes.ORIGENERATOR_SOURCE)

        assert (encoded_with, upscaled.name) == ([], "scene one_topaz.mp4")

    def test_none_is_upscaled_again_while_the_gallery_cannot_be_read(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config():
                touch_video(lanes.upscale_of(lanes.ORIGENERATOR_SOURCE, "portrait", "scene one"))
            (root / "gallery.db").write_bytes(b"not a database, made up for this test")
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
