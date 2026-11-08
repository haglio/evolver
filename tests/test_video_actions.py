from __future__ import annotations

import json
import sqlite3
import unittest

from tasks import video_actions
from tasks.origenerator_metadata import PUBLISHED_ACTIONS
from tests.temp_helpers import LaneLibrary, touch_video, workspace_temp_dir, write_sidecar
from tests.test_origenerator_metadata import _make_db, _row
from util import sidecar


def _publish_actions(db, actions_of_each_video):
    conn = sqlite3.connect(db)
    conn.execute(f"ALTER TABLE generations ADD COLUMN {PUBLISHED_ACTIONS} TEXT")
    conn.executemany(f"UPDATE generations SET {PUBLISHED_ACTIONS} = ? WHERE prompt_id = ?",
                     [(json.dumps(actions), prompt_id)
                      for prompt_id, actions in actions_of_each_video.items()])
    conn.commit()
    conn.close()


class TestAVideoOrigeneratorMade(unittest.TestCase):
    def test_its_labels_are_copied_from_the_gallery_into_its_record_beside_its_action(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", outputs=["wan22_i2v_00001_.mp4"])])
            _publish_actions(db, {"vid-1": ["alpha", "beta"]})
            with lib.config(ORIGENERATOR_DB_PATH=db):
                touch_video(lib.sorted_dir / "origenerator" / "portrait" / "wan22_i2v_00001_.mp4")
                record = sidecar.sidecar_path(
                    lib.outbox / "portrait" / "origenerator" / "wan22_i2v_00001__topaz.mp4")
                write_sidecar(record, {"video": {"action": "Gamma"}})

                video_actions.run()

                recorded = sidecar.read(record)

        assert recorded == {"video": {"action": "Gamma", "labels": ["alpha", "beta"]}}


class TestAVideoOrigeneratorBroughtInFromAnotherSite(unittest.TestCase):
    def test_its_labels_are_copied_into_the_record_of_the_upscale_it_brought_in(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = root / "origenerator.db"
            upscale = lib.outbox / "landscape" / "example-site" / "video one_topaz.mp4"
            brought_in = _row("site-1", outputs=[])
            brought_in["output_files"] = json.dumps([{"filename": upscale.name,
                                                      "library_path": str(upscale)}])
            _make_db(db, [brought_in])
            _publish_actions(db, {"site-1": ["beta"]})
            with lib.config(ORIGENERATOR_DB_PATH=db):
                touch_video(lib.sorted_dir / "example-site" / "landscape" / "video one.mp4")
                record = sidecar.sidecar_path(upscale)
                write_sidecar(record, {"video": {"action": "Gamma"}})

                video_actions.run()

                recorded = sidecar.read(record)

        assert recorded == {"video": {"action": "Gamma", "labels": ["beta"]}}


class TestAVideoWithNoLabelsToCopy(unittest.TestCase):
    def test_one_the_gallery_has_published_no_labels_for_keeps_its_record_as_it_is(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", outputs=["wan22_i2v_00001_.mp4"])])
            with lib.config(ORIGENERATOR_DB_PATH=db):
                touch_video(lib.sorted_dir / "origenerator" / "portrait" / "wan22_i2v_00001_.mp4")
                touch_video(lib.sorted_dir / "example-site" / "portrait" / "video two.mp4")
                records = [sidecar.sidecar_path(lib.outbox / "portrait" / source / name)
                           for source, name in (("origenerator", "wan22_i2v_00001__topaz.mp4"),
                                                ("example-site", "video two_topaz.mp4"))]
                for record in records:
                    write_sidecar(record, {"video": {"action": "Gamma", "labels": ["alpha"]}})

                video_actions.run()

                recorded = [sidecar.read(record) for record in records]

        assert recorded == [{"video": {"action": "Gamma", "labels": ["alpha"]}}] * 2

    def test_one_whose_record_its_scrape_has_not_written_yet_is_given_none(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", outputs=["wan22_i2v_00001_.mp4"])])
            _publish_actions(db, {"vid-1": ["alpha"]})
            with lib.config(ORIGENERATOR_DB_PATH=db):
                touch_video(lib.sorted_dir / "origenerator" / "portrait" / "wan22_i2v_00001_.mp4")

                video_actions.run()

                written = sidecar.sidecar_path(
                    lib.outbox / "portrait" / "origenerator" / "wan22_i2v_00001__topaz.mp4").exists()

        assert not written


class TestWhatARunSays(unittest.TestCase):
    def test_it_counts_the_records_it_gave_actions_apart_from_those_already_carrying_them(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", outputs=["wan22_i2v_00001_.mp4"]),
                          _row("vid-2", outputs=["wan22_i2v_00002_.mp4"])])
            _publish_actions(db, {"vid-1": ["alpha"], "vid-2": ["beta"]})
            with lib.config(ORIGENERATOR_DB_PATH=db):
                for number, actions in (("1", []), ("2", ["beta"])):
                    touch_video(lib.sorted_dir / "origenerator" / "portrait" / f"wan22_i2v_0000{number}_.mp4")
                    write_sidecar(sidecar.sidecar_path(
                        lib.outbox / "portrait" / "origenerator" / f"wan22_i2v_0000{number}__topaz.mp4"),
                        {"video": {"labels": actions}})

                result = video_actions.run()

        assert (result.copied, result.already) == (1, 1)

    def test_a_gallery_it_cannot_read_leaves_every_record_for_a_run_that_can(self):
        with workspace_temp_dir() as root:
            lib = LaneLibrary(root)
            with lib.config(ORIGENERATOR_DB_PATH=root / "no gallery here.db"):
                touch_video(lib.sorted_dir / "origenerator" / "portrait" / "wan22_i2v_00001_.mp4")
                record = sidecar.sidecar_path(
                    lib.outbox / "portrait" / "origenerator" / "wan22_i2v_00001__topaz.mp4")
                write_sidecar(record, {"video": {"labels": ["alpha"]}})

                result = video_actions.run()

                recorded = sidecar.read(record)

        assert (recorded, result.ok) == ({"video": {"labels": ["alpha"]}}, True)
