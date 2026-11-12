from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from app_support import provenance

from tasks import origenerator_metadata as om
from tests.temp_helpers import workspace_temp_dir
from util import provenance as provenance_of_evolver
from util.provenance import METHOD, METHOD_VERSION

_SCHEMA = (
    "CREATE TABLE generations ("
    " prompt_id TEXT, workflow_name TEXT, workflow_version TEXT,"
    " positive_prompt TEXT, negative_prompt TEXT, seed INTEGER,"
    " params_json TEXT, output_files TEXT, created_at TEXT)"
)


_ROW_DEFAULTS = {
    "workflow": "wan22_i2v", "version": "v001", "pos": None, "neg": None,
    "seed": None, "params": None, "outputs": (), "created": None,
}


def _row(prompt_id, **given):
    unknown = given.keys() - _ROW_DEFAULTS.keys()
    if unknown:
        raise TypeError(f"unknown row field: {', '.join(sorted(unknown))}")
    fields = {**_ROW_DEFAULTS, **given}
    return {
        "prompt_id": prompt_id,
        "workflow_name": fields["workflow"],
        "workflow_version": fields["version"],
        "positive_prompt": fields["pos"],
        "negative_prompt": fields["neg"],
        "seed": fields["seed"],
        "params_json": json.dumps(fields["params"] or {}),
        "output_files": json.dumps(
            [{"filename": name, "subfolder": "video", "type": "output"}
             for name in fields["outputs"]]
        ),
        "created_at": fields["created"],
    }


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    conn.executemany(
        "INSERT INTO generations (prompt_id, workflow_name, workflow_version,"
        " positive_prompt, negative_prompt, seed, params_json, output_files, created_at)"
        " VALUES (:prompt_id, :workflow_name, :workflow_version, :positive_prompt,"
        " :negative_prompt, :seed, :params_json, :output_files, :created_at)",
        rows,
    )
    conn.commit()
    conn.close()


def _stamp_row(path, prompt_id, stamp):
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE generations ADD COLUMN provenance TEXT")
    conn.execute("UPDATE generations SET provenance = ? WHERE prompt_id = ?",
                 (json.dumps(stamp), prompt_id))
    conn.commit()
    conn.close()


def _generation_of(db, video: str) -> dict:
    return om.generation_records(db_path=db)(Path(video))


class TestWhatMadeTheVideo(unittest.TestCase):
    def test_the_generation_s_workflow_and_its_version_are_recorded_as_what_made_it(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", workflow="wan22_i2v", version="v007",
                               outputs=["wan22_i2v_00001_.mp4"])])
            generation = _generation_of(db, "wan22_i2v_00001_.mp4")

        assert generation == {"schema": provenance.SCHEMA, "app": "origenerator", "app_commit": None, "app_dirty": None, METHOD: "wan22_i2v", METHOD_VERSION: "v007", "stamped_at": None}

    def test_the_importer_s_placeholders_are_recorded_as_unknown(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", workflow="unknown", version="imported",
                               outputs=["wan22_i2v_00001_.mp4"])])
            generation = _generation_of(db, "wan22_i2v_00001_.mp4")

        assert (generation[METHOD], generation[METHOD_VERSION]) == (None, None), "carried as it stands, \"imported\" reads to a sweep comparing versions as a version"

    def test_a_record_the_gallery_keeps_of_its_own_is_carried_as_it_stands(self):
        its_own = {
            "schema": provenance.SCHEMA, "app": "origenerator",
            "app_commit": "0123abc", "app_dirty": False,
            METHOD: "wan22_i2v", METHOD_VERSION: "v007",
            "stamped_at": "2026-09-01T20:15:00+00:00",
        }
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", workflow="wan22_i2v", version="v007",
                               outputs=["wan22_i2v_00001_.mp4"])])
            _stamp_row(db, "vid-1", its_own)
            generation = _generation_of(db, "wan22_i2v_00001_.mp4")

        assert generation == its_own

    def test_a_video_the_gallery_did_not_make_was_made_by_origenerator_and_nothing_more_is_known(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [])
            generation = _generation_of(db, "wan22_i2v_00009_.mp4")

        assert generation == provenance_of_evolver.reconstructed("origenerator")

    def test_a_video_whose_name_was_given_a_number_by_the_library_is_still_matched(self):
        with workspace_temp_dir() as root:
            db = root / "origenerator.db"
            _make_db(db, [_row("vid-1", workflow="wan22_i2v", version="v007",
                               outputs=["wan22_i2v_00001_.mp4"])])
            generation = _generation_of(db, "wan22_i2v_00001_ (2).mp4")

        assert generation[METHOD] == "wan22_i2v"


if __name__ == "__main__":
    unittest.main()
