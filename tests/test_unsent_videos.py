from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from tasks import unsent_videos
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir
from util import lanes, script_library

_SCHEMA = (
    "CREATE TABLE generations ("
    " prompt_id TEXT, output_files TEXT,"
    " evolver_exported_at TEXT, evolver_unsent_at TEXT,"
    " genau_exported_at TEXT, genau_unsent_at TEXT)"
)


def _gallery(path: Path, rows) -> Path:
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    for prompt_id, filename, unsent_column in rows:
        outputs = json.dumps([{"filename": filename, "subfolder": "video"}])
        conn.execute("INSERT INTO generations (prompt_id, output_files) VALUES (?, ?)",
                     (prompt_id, outputs))
        if unsent_column:
            conn.execute(
                f"UPDATE generations SET {unsent_column} = '2026-01-02 03:04:05'"
                " WHERE prompt_id = ?", (prompt_id,))
    conn.commit()
    conn.close()
    return path


class TestTheEvolverLane(unittest.TestCase):
    def test_a_withdrawn_clip_goes_from_the_outbox_and_from_1_sorted(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            source = lanes.ORIGENERATOR_SOURCE
            db = _gallery(root / "gallery.db", [("p1", "made_00001.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                sorted_copy = touch_video(
                    lib.sorted_dir / source / "portrait" / "made_00001.mp4")
                upscale = touch_video(
                    lib.kino_upscales / "portrait" / source / "made_00001_topaz.mp4")

                result = unsent_videos.run()

                assert not upscale.exists()
                assert not sorted_copy.exists()
        assert result.deleted == 2

    def test_a_withdrawn_clip_takes_each_copys_funscript_and_its_mark_along(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            source = lanes.ORIGENERATOR_SOURCE
            db = _gallery(root / "gallery.db", [("p1", "made_00006.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                copies = (touch_video(lib.sorted_dir / source / "portrait" / "made_00006.mp4"),
                          touch_video(lib.kino_upscales / "portrait" / source / "made_00006_topaz.mp4"))
                scripts = [script_library.script_path_for_video(copy) for copy in copies]
                for script in scripts:
                    touch_video(script)
                    script_library.mark_generated(script)

                result = unsent_videos.run()

                for script in scripts:
                    assert not script.exists()
                    assert not script_library.is_marked_generated(script)
        assert result.deleted_scripts == 2

    def test_the_funscript_still_where_a_condemned_upscale_was_filed_goes_too(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            source = lanes.ORIGENERATOR_SOURCE
            db = _gallery(root / "gallery.db", [("p1", "made_00007.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                touch_video(lib.trash / "made_00007_topaz.mp4")
                touch_video(lib.sorted_dir / source / "portrait" / "made_00007.mp4")
                left_behind = touch_video(script_library.script_path_for_video(
                    lib.kino_upscales / "portrait" / source / "made_00007_topaz.mp4"))

                unsent_videos.run()

                assert not left_behind.exists()

    def test_a_funscript_that_will_not_delete_is_left_for_the_next_run(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            source = lanes.ORIGENERATOR_SOURCE
            db = _gallery(root / "gallery.db", [("p1", "made_00008.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                sorted_copy = touch_video(lib.sorted_dir / source / "portrait" / "made_00008.mp4")
                script = touch_video(script_library.script_path_for_video(sorted_copy))

                with patch("tasks.unsent_videos.script_library.delete_script",
                           side_effect=PermissionError("in use")):
                    result = unsent_videos.run()

                assert script.exists()
        assert (result.deleted, result.deleted_scripts, result.failed) == (1, 0, 1)

    def test_a_clip_still_in_the_inbox_goes_before_it_is_ever_sorted(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p1", "made_00002.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                waiting = touch_video(
                    lib.inbox / lanes.ORIGENERATOR_SOURCE / "made_00002.mp4")

                unsent_videos.run()

                assert not waiting.exists()

    def test_a_send_that_still_stands_is_left_alone(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p1", "made_00003.mp4", None)])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                kept = touch_video(
                    lib.kino_upscales / "portrait" / lanes.ORIGENERATOR_SOURCE
                    / "made_00003_topaz.mp4")

                result = unsent_videos.run()

                assert kept.exists()
        assert result.deleted == 0

    def test_a_clip_this_library_never_took_is_no_error(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p1", "made_00004.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                result = unsent_videos.run()

        assert (result.deleted, result.failed) == (0, 0)

    def test_the_copy_keeps_the_uniquifier_the_inbox_gave_it(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p1", "made_00005.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                second = touch_video(
                    lib.kino_upscales / "landscape" / lanes.ORIGENERATOR_SOURCE
                    / "made_00005 (2)_topaz.mp4")

                unsent_videos.run()

                assert not second.exists()

    def test_a_copy_that_reappears_is_deleted_again(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p1", "made_00010.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                copy = lib.kino_upscales / "portrait" / lanes.ORIGENERATOR_SOURCE / "made_00010_topaz.mp4"
                touch_video(copy)
                unsent_videos.run()
                touch_video(copy)

                again = unsent_videos.run()

                assert not copy.exists()
            with closing(sqlite3.connect(db)) as gallery:
                stamps = gallery.execute("SELECT evolver_unsent_at FROM generations").fetchall()
        assert again.deleted == 1
        assert stamps == [("2026-01-02 03:04:05",)], "a take-back is a standing mark on the row, never cleared from this side"

    def test_a_source_stays_while_its_upscale_will_not_go(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            source = lanes.ORIGENERATOR_SOURCE
            db = _gallery(root / "gallery.db", [("p1", "made_00007.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                sorted_copy = touch_video(
                    lib.sorted_dir / source / "portrait" / "made_00007.mp4")
                locked = touch_video(
                    lib.kino_upscales / "portrait" / source / "made_00007_topaz.mp4")
                with locked.open("a"):
                    result = unsent_videos.run()

                assert sorted_copy.exists(), "a source deleted first is a source the correspondence check finds with no upscale"
        assert result.failed == 1


class TestTheGenauLane(unittest.TestCase):
    def test_a_withdrawn_loop_goes_from_the_folder_genau_plays_from(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p2", "loop_00001.mp4", "genau_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                delivered = touch_video(lib.genau_flicks / "2D" / "AI" / "loop_00001_topaz.mp4")

                unsent_videos.run()

                assert not delivered.exists()

    def test_withdrawing_from_one_lane_leaves_the_other_lanes_copy(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p3", "both_00001.mp4", "genau_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                kept = touch_video(
                    lib.kino_upscales / "portrait" / lanes.ORIGENERATOR_SOURCE
                    / "both_00001_topaz.mp4")
                delivered = touch_video(lib.genau_flicks / "2D" / "AI" / "both_00001_topaz.mp4")

                unsent_videos.run()

                assert kept.exists()
                assert not delivered.exists()


def _gallery_of_videos_with_sound(path: Path, stems) -> Path:
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    for n, stem in enumerate(stems):
        outputs = json.dumps([{"filename": f"{stem}-audio.mp4", "subfolder": "video"},
                              {"filename": f"{stem}.mp4", "subfolder": "video",
                               "role": unsent_videos.SILENT_COPY_ROLE}])
        conn.execute("INSERT INTO generations (prompt_id, output_files) VALUES (?, ?)",
                     (f"p{n}", outputs))
    conn.commit()
    conn.close()
    return path


class TestASoundlessCopy(unittest.TestCase):
    def test_it_leaves_genaus_folder_once_the_video_with_its_sound_is_there(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery_of_videos_with_sound(root / "gallery.db", ["loop_00009"])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                sounded = touch_video(lib.genau_flicks / "2D" / "AI" / "loop_00009-audio_topaz.mp4")
                soundless = touch_video(lib.genau_flicks / "2D" / "AI" / "loop_00009_topaz.mp4")

                unsent_videos.run()

                assert sounded.exists()
                assert not soundless.exists()

    def test_it_stays_where_it_is_the_only_copy_of_its_video(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery_of_videos_with_sound(root / "gallery.db", ["loop_00010"])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                soundless = touch_video(lib.genau_flicks / "2D" / "AI" / "loop_00010_topaz.mp4")

                unsent_videos.run()

                assert soundless.exists()

    def test_it_leaves_the_library_once_the_video_with_its_sound_has_its_upscale(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            source = lanes.ORIGENERATOR_SOURCE
            db = _gallery_of_videos_with_sound(root / "gallery.db", ["made_00011"])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                sounded = touch_video(lib.kino_upscales / "landscape" / source / "made_00011-audio_topaz.mp4")
                soundless = (touch_video(lib.kino_upscales / "landscape" / source / "made_00011_topaz.mp4"),
                             touch_video(lib.sorted_dir / source / "landscape" / "made_00011.mp4"))

                result = unsent_videos.run()

                assert sounded.exists()
                assert not any(copy.exists() for copy in soundless)
        assert result.deleted == 2


class TestAGalleryThisCannotRead(unittest.TestCase):
    def test_a_database_that_is_not_there_is_no_work_and_no_failure(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "absent.db"):
                result = unsent_videos.run()

        assert (result.deleted, result.failed) == (0, 0)

    def test_a_gallery_from_before_the_columns_existed_withdraws_nothing(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            path = root / "old.db"
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE generations (prompt_id TEXT, output_files TEXT)")
            conn.execute("INSERT INTO generations VALUES ('p1', '[]')")
            conn.commit()
            conn.close()
            with lib.config(ORIGENERATOR_DB_PATH=path):
                kept = touch_video(
                    lib.kino_upscales / "portrait" / lanes.ORIGENERATOR_SOURCE / "old_topaz.mp4")

                result = unsent_videos.run()

                assert kept.exists()
        assert result.deleted == 0
