"""Clips Origenerator has taken back, deleted wherever this library filed them.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from tasks import withdrawn
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir
from util import lanes

_SCHEMA = (
    "CREATE TABLE generations ("
    " prompt_id TEXT, output_files TEXT,"
    " evolver_exported_at TEXT, evolver_unsent_at TEXT,"
    " genau_exported_at TEXT, genau_unsent_at TEXT)"
)


def _gallery(path: Path, rows) -> Path:
    """An Origenerator gallery holding *rows* -- (prompt_id, filename, column)."""
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


def _sidecar(library: LaneLibrary, *parts) -> Path:
    path = library.metadata.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
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
                    lib.outbox / "portrait" / source / "made_00001_topaz.mp4")

                result = withdrawn.run()

                self.assertFalse(upscale.exists())
                self.assertFalse(sorted_copy.exists())
        self.assertEqual(result.deleted, 2)

    def test_a_clip_still_in_the_inbox_goes_before_it_is_ever_sorted(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p1", "made_00002.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                waiting = touch_video(
                    lib.inbox / lanes.ORIGENERATOR_SOURCE / "made_00002.mp4")

                withdrawn.run()

                self.assertFalse(waiting.exists())

    def test_a_send_that_still_stands_is_left_alone(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p1", "made_00003.mp4", None)])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                kept = touch_video(
                    lib.outbox / "portrait" / lanes.ORIGENERATOR_SOURCE
                    / "made_00003_topaz.mp4")

                result = withdrawn.run()

                self.assertTrue(kept.exists())
        self.assertEqual(result.deleted, 0)

    def test_a_clip_this_library_never_took_is_no_error(self):
        # The withdrawal is a standing answer rather than a request that drains,
        # so it is read again on every run long after the copies have gone.
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p1", "made_00004.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                result = withdrawn.run()

        self.assertEqual((result.deleted, result.failed), (0, 0))

    def test_the_copy_keeps_the_uniquifier_the_inbox_gave_it(self):
        # Two clips of one name reach the inbox and the second is filed as
        # "name (2)"; the upscale carries that through, and a withdrawal has to
        # follow it or the clip it names is never found.
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p1", "made_00005.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                second = touch_video(
                    lib.outbox / "landscape" / lanes.ORIGENERATOR_SOURCE
                    / "made_00005 (2)_topaz.mp4")

                withdrawn.run()

                self.assertFalse(second.exists())

    def test_the_clip_takes_its_metadata_with_it(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            source = lanes.ORIGENERATOR_SOURCE
            db = _gallery(root / "gallery.db", [("p1", "made_00006.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                touch_video(lib.outbox / "portrait" / source / "made_00006_topaz.mp4")
                record = _sidecar(lib, "2D", "AI", "2_outbox", "upscaled_by_orientation",
                                  "portrait", source, "made_00006_topaz.json")

                result = withdrawn.run()

                self.assertFalse(record.exists())
        self.assertEqual(result.deleted_metadata, 1)

    def test_an_outbox_copy_that_will_not_go_keeps_its_source_beside_it(self):
        # 1_sorted and the outbox are held in one-to-one correspondence, and a
        # missing counterpart pops a dialog -- so a locked upscale leaves its
        # source where it is, for the next run to take both together.
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            source = lanes.ORIGENERATOR_SOURCE
            db = _gallery(root / "gallery.db", [("p1", "made_00007.mp4", "evolver_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                sorted_copy = touch_video(
                    lib.sorted_dir / source / "portrait" / "made_00007.mp4")
                locked = touch_video(
                    lib.outbox / "portrait" / source / "made_00007_topaz.mp4")
                with locked.open("a"):
                    result = withdrawn.run()

                self.assertTrue(sorted_copy.exists())
        self.assertEqual(result.failed, 1)


class TestTheGenauLane(unittest.TestCase):
    def test_a_withdrawn_loop_goes_from_the_folder_genau_plays_from(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p2", "loop_00001.mp4", "genau_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                delivered = touch_video(lib.genau_clips / "loop_00001_topaz.mp4")

                withdrawn.run()

                self.assertFalse(delivered.exists())

    def test_withdrawing_from_one_lane_leaves_the_other_lanes_copy(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = _gallery(root / "gallery.db", [("p3", "both_00001.mp4", "genau_unsent_at")])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                kept = touch_video(
                    lib.outbox / "portrait" / lanes.ORIGENERATOR_SOURCE
                    / "both_00001_topaz.mp4")
                delivered = touch_video(lib.genau_clips / "both_00001_topaz.mp4")

                withdrawn.run()

                self.assertTrue(kept.exists())
                self.assertFalse(delivered.exists())


class TestAGalleryThisCannotRead(unittest.TestCase):
    def test_a_database_that_is_not_there_is_no_work_and_no_failure(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "absent.db"):
                result = withdrawn.run()

        self.assertEqual((result.deleted, result.failed), (0, 0))

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
                    lib.outbox / "portrait" / lanes.ORIGENERATOR_SOURCE / "old_topaz.mp4")

                result = withdrawn.run()

                self.assertTrue(kept.exists())
        self.assertEqual(result.deleted, 0)
